import os
import time
import sqlite3
import requests
from google import genai
from datetime import datetime

# 1. Grab Environment Variables DIRECTLY
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_HOST = "cricbuzz-cricket.p.rapidapi.com"

# --- SAFETY CHECK ---
if not GEMINI_API_KEY or not RAPID_API_KEY or not BOT_TOKEN:
    print("🚨 SYSTEM HALTED: Missing API Keys!")
    time.sleep(60)
    exit()

# 2. Setup Gemini AI 
client = genai.Client() 

# 3. Database Setup
conn = sqlite3.connect("cricket.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, toss_done INTEGER DEFAULT 0)")
conn.commit()

# --- Command Tracking ---
last_update_id = None

def send_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_ai_news(prompt):
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=f"Format this as professional cricket news for WhatsApp: {prompt}"
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

# =====================
# THE BULLETPROOF SEARCH
# =====================
def extract_matches_from_api(data):
    raw_matches = []
    # This recursively digs through every single nested folder in the API
    def find_matches(obj):
        if isinstance(obj, dict):
            # If we find a folder that has all 3 of these, we found a match!
            if 'matchId' in obj and 'team1' in obj and 'team2' in obj:
                raw_matches.append(obj)
            for k, v in obj.items():
                find_matches(v)
        elif isinstance(obj, list):
            for item in obj:
                find_matches(item)
                
    find_matches(data)
    return raw_matches

# =====================
# COMMAND HANDLER
# =====================
def handle_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 5} 
    
    if last_update_id:
        params["offset"] = last_update_id + 1
        
    try:
        res = requests.get(url, params=params, timeout=10).json()
        if not res.get("ok"): return
        
        for update in res.get("result", []):
            last_update_id = update["update_id"]
            
            # Check for BOTH regular messages AND channel posts
            msg_data = update.get("message") or update.get("channel_post")
            
            if not msg_data: 
                continue
            
            text = msg_data.get("text", "")
            
            if "/score" in text:
                send_telegram("🏏 Let me check the live scores for you...")
                fetch_live_summary()
                
    except Exception as e:
        print(f"Command Error: {e}")

def fetch_live_summary():
    url = f"https://{RAPID_HOST}/matches/v1/live"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": RAPID_HOST}
    
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        
        # Use our new bulletproof search algorithm
        matches = extract_matches_from_api(res)
        
        matches_found = []
        for m in matches:
            t1 = m.get('team1', {}).get('teamSName', 'T1')
            t2 = m.get('team2', {}).get('teamSName', 'T2')
            state = m.get('state', 'Live')
            matches_found.append(f"{t1} vs {t2} ({state})")
        
        if not matches_found:
            send_telegram("There are no live international matches at the moment.")
            return
            
        prompt = f"User asked for a score update. Here are the live matches: {', '.join(matches_found)}. Write a very brief, punchy bulleted summary."
        send_telegram(get_ai_news(prompt))
    except Exception as e:
        send_telegram("⚠️ Sorry, I hit an error pulling the scores.")

# =====================
# BACKGROUND POLLING
# =====================
def process_matches():
    url = f"https://{RAPID_HOST}/matches/v1/live"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": RAPID_HOST}
    
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        matches = extract_matches_from_api(res)
        
        for m in matches:
            m_id = str(m['matchId'])
            t1 = m.get('team1', {}).get('teamSName', 'T1')
            t2 = m.get('team2', {}).get('teamSName', 'T2')
            m_name = f"{t1} vs {t2}"
            
            process_single_match(m_id, m_name)
    except Exception as e:
        pass

def process_single_match(m_id, m_name):
    url = f"https://{RAPID_HOST}/mcenter/v1/{m_id}/comm"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": RAPID_HOST}
    
    try:
        data = requests.get(url, headers=headers, timeout=15).json()
        score_info = data.get('miniscore', {})
        cur_overs = float(score_info.get('overs', 0))
        cur_score = f"{score_info.get('batTeamScore', '0')}/{score_info.get('batTeamWkts', '0')}"
        
        row = cursor.execute("SELECT last_over, toss_done FROM state WHERE m_id=?", (m_id,)).fetchone()
        last_over, toss_done = (row[0], row[1]) if row else (0.0, 0)

        if not toss_done:
            status = score_info.get('matchHeader', {}).get('status', "")
            if "won the toss" in status.lower():
                eid = f"{m_id}_TOSS"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    msg = get_ai_news(f"TOSS: {m_name}. {status}")
                    send_telegram(msg)
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))
                    toss_done = 1

        if int(cur_overs // 10) > int(last_over // 10) and cur_overs >= 10:
            m_stone = int((cur_overs // 10) * 10)
            eid = f"{m_id}_O_{m_stone}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = get_ai_news(f"{m_stone} OVER UPDATE: {m_name} is {cur_score} after {cur_overs} overs.")
                send_telegram(msg)
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        for comm in data.get('commentaryList', [])[:5]:
            comm_text = comm.get('commText', "")
            event_type = None
            if "reach" in comm_text.lower() and "50" in comm_text: event_type = "50"
            elif "reach" in comm_text.lower() and "100" in comm_text: event_type = "100"

            if event_type:
                eid = f"{m_id}_{event_type}_{hash(comm_text)}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    msg = get_ai_news(f"Milestone: Player reached {event_type} in {m_name}. Score: {cur_score}. Info: {comm_text}")
                    send_telegram(msg)
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        cursor.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (m_id, cur_overs, toss_done))
        conn.commit()
    except Exception as e:
        pass

if __name__ == "__main__":
    print("🚀 Cricket Newsroom Worker Starting...")
    send_telegram("✅ Cricket Newsroom Bot is now online. Type /score to check live matches!")
    while True:
        handle_commands() 
        process_matches() 
        time.sleep(25)
