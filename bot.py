import os
import time
import sqlite3
import requests
from google import genai
from datetime import datetime
from dotenv import load_dotenv

# 1. Load Environment Variables (Railway handles this automatically)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_HOST = "cricbuzz-cricket.p.rapidapi.com"

# 2. Setup Gemini AI using the NEW google-genai library
client = genai.Client(api_key=GEMINI_API_KEY)

# 3. Database Setup (Persists safely on Railway)
conn = sqlite3.connect("cricket.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, toss_done INTEGER DEFAULT 0)")
conn.commit()

def send_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_ai_news(prompt):
    try:
        # Updated syntax for the new google-genai SDK
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=f"Format this as professional cricket news for WhatsApp: {prompt}"
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

def process_matches():
    url = f"https://{RAPID_HOST}/matches/v1/live"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": RAPID_HOST}
    
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        # Strictly look for International matches
        intl = [s for s in res.get('typeMatches', []) if s.get('matchType') == 'intl']
        
        for section in intl:
            for match in section.get('seriesMatches', []):
                m = match.get('seriesAdWrapper', {}).get('matchScoreDetails', {})
                if not m: continue
                
                m_id = str(m['matchId'])
                m_name = f"{m['team1ShortName']} vs {m['team2ShortName']}"
                
                process_single_match(m_id, m_name)
    except Exception as e:
        print(f"Fetch Error: {e}")

def process_single_match(m_id, m_name):
    # Fetch miniscore and commentary
    url = f"https://{RAPID_HOST}/mcenter/v1/{m_id}/comm"
    headers = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": RAPID_HOST}
    
    try:
        data = requests.get(url, headers=headers, timeout=15).json()
        score_info = data.get('miniscore', {})
        cur_overs = float(score_info.get('overs', 0))
        cur_score = f"{score_info.get('batTeamScore', '0')}/{score_info.get('batTeamWkts', '0')}"
        
        row = cursor.execute("SELECT last_over, toss_done FROM state WHERE m_id=?", (m_id,)).fetchone()
        last_over, toss_done = (row[0], row[1]) if row else (0.0, 0)

        # 1. Toss Logic
        if not toss_done:
            status = score_info.get('matchHeader', {}).get('status', "")
            if "won the toss" in status.lower():
                eid = f"{m_id}_TOSS"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    msg = get_ai_news(f"TOSS: {m_name}. {status}")
                    send_telegram(msg)
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))
                    toss_done = 1

        # 2. Over Milestones (10, 20, 30)
        if int(cur_overs // 10) > int(last_over // 10) and cur_overs >= 10:
            m_stone = int((cur_overs // 10) * 10)
            eid = f"{m_id}_O_{m_stone}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = get_ai_news(f"{m_stone} OVER UPDATE: {m_name} is {cur_score} after {cur_overs} overs.")
                send_telegram(msg)
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # 3. Commentary Milestones (50s / 100s)
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

        # Update State
        cursor.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (m_id, cur_overs, toss_done))
        conn.commit()
    except Exception as e:
        pass

if __name__ == "__main__":
    print("🚀 Cricket Newsroom Worker Starting...")
    send_telegram("✅ Cricket Newsroom Bot is now online and monitoring matches!")
    while True:
        process_matches()
        time.sleep(30) # Efficient polling for your 1000/hr limit
