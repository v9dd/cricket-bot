import requests
import os
import time
import sqlite3
from bs4 import BeautifulSoup
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not BOT_TOKEN:
    print("🚨 SYSTEM HALTED: Missing Telegram Token!")
    time.sleep(60)
    exit()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

conn = sqlite3.connect("cricket.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, toss_done INTEGER DEFAULT 0)")
conn.commit()

match_state = {}
last_update_id = None

def send_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def is_international(match_title):
    title = match_title.upper()
    if "WOMEN" in title or " U19" in title or "TROPHY" in title or "LEAGUE" in title:
        return False
    intl_formats = ["TEST", "ODI", "T20I", "WORLD CUP"]
    if any(fmt in title for fmt in intl_formats):
        return True
    countries = ["INDIA", "AUSTRALIA", "ENGLAND", "NEW ZEALAND", "SOUTH AFRICA", "PAKISTAN", "SRI LANKA", "WEST INDIES", "BANGLADESH", "ZIMBABWE", "AFGHANISTAN", "IRELAND"]
    if sum(1 for c in countries if c in title) >= 2:
        return True
    return False

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
            msg_data = update.get("message") or update.get("channel_post")
            if not msg_data: continue
            text = msg_data.get("text", "")
            
            if "/score" in text:
                send_telegram("🏏 *Fetching live international scores...*")
                matches = scrape_match_links()
                if not matches:
                    send_telegram("⚠️ There are no live international matches playing right now.")
                    continue
                
                summary_data = []
                for name, link in matches[:5]:
                    score = scrape_instant_score(link)
                    summary_data.append(f"🔹 *{name}*\n📊 {score}")
                
                send_telegram("🏆 *LIVE INTERNATIONAL SCORES* 🏆\n\n" + "\n\n".join(summary_data))
    except Exception:
        pass

def scrape_match_links():
    url = "https://www.cricbuzz.com/cricket-match/live-scores"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        main_container = soup.find("div", class_="flex flex-col gap-2")
        matches = []
        if not main_container: return matches
        
        for block in main_container.find_all("div", recursive=False):
            for card in block.select("a.w-full.bg-cbWhite"):
                name = card.get("title", "").strip()
                if not name: continue
                if is_international(name):
                    link = "https://www.cricbuzz.com" + card["href"]
                    matches.append((name, link))
        return matches
    except Exception:
        return []

def scrape_instant_score(match_url):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return "Score not available yet"
        
        score_parts = score_div.find_all("div")
        runs = score_parts[0].get_text(strip=True)
        wickets = score_parts[1].get_text(strip=True).replace("-", "")
        overs = score_parts[2].get_text(strip=True).replace("(", "").replace(")", "")
        return f"{runs}-{wickets} ({overs} overs)"
    except:
        return "Error loading score"

def fetch_toss_update(match_url, match_name):
    if match_url not in match_state:
        match_state[match_url] = {"toss_sent": False}
    if match_state[match_url]["toss_sent"]: return

    scorecard_url = match_url.replace("live-cricket-scores", "live-cricket-scorecard").replace("www.cricbuzz.com", "m.cricbuzz.com")
    try:
        response = requests.get(scorecard_url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return

        soup = BeautifulSoup(response.text, "html.parser")
        toss_label = soup.find(lambda tag: tag.name == "div" and "font-bold" in tag.get("class", []) and "Toss" in tag.get_text())
        if not toss_label: return

        toss_text = toss_label.find_next("div").get_text(strip=True)
        match_state[match_url]["toss_sent"] = True

        send_telegram(f"🪙 *TOSS UPDATE* 🪙\n\n*{match_name}*\n\n{toss_text}\n\n🔗 [Match Link]({match_url})")
    except Exception:
        pass

def fetch_match_update(match_url, match_name):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, "html.parser")

        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return

        score_parts = score_div.find_all("div")
        runs = score_parts[0].get_text(strip=True)
        wickets = score_parts[1].get_text(strip=True).replace("-", "")
        overs = score_parts[2].get_text(strip=True).replace("(", "").replace(")", "")
        score = f"{runs}-{wickets}"
        
        try: cur_overs = float(overs)
        except: cur_overs = 0.0

        commentary_main = soup.find("div", class_=lambda x: x and "leading-6" in x)
        if not commentary_main: return
        
        event_blocks = commentary_main.find_all("div", recursive=False)
        if not event_blocks: return
        
        target_block = event_blocks[0] if "." in overs else (event_blocks[1] if len(event_blocks) > 1 else event_blocks[0])
        flex_row = target_block.find("div", class_=lambda x: x and "flex" in x and "gap-4" in x)
        if not flex_row: return
        
        event_text = flex_row.find_all("div", recursive=False)[1].get_text(strip=True)
        event_lower = event_text.lower()

        m_id = match_url.split("/")[-2] if "/" in match_url else str(hash(match_name))
        row = cursor.execute("SELECT last_over, toss_done FROM state WHERE m_id=?", (m_id,)).fetchone()
        last_over, toss_done = (row[0], row[1]) if row else (0.0, 0)
        
        messages_to_send = []
        
        # --- EXTREME CASE 1: MATCH ENDED (Targets Chased / Draws) ---
        is_match_over = any(phrase in event_lower for phrase in ["won by", "win by", "match drawn", "match tied", "abandoned", "no result"])
        if is_match_over:
            eid = f"{m_id}_MATCH_END"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                messages_to_send.append(
                    f"🏆 *MATCH COMPLETED: {match_name}*\n\n"
                    f"🎯 *Result:* {event_text}\n"
                    f"📊 *Final Score:* {score} ({overs})\n"
                    f"🔗 [Match Link]({match_url})"
                )
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # --- EXTREME CASE 2: RAIN DELAYS / INTERRUPTIONS ---
        is_delayed = any(phrase in event_lower for phrase in ["rain stops play", "match delayed", "bad light"])
        if is_delayed:
            eid = f"{m_id}_DELAY_{cur_overs}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                messages_to_send.append(
                    f"⚠️ *MATCH DELAYED: {match_name}*\n\n"
                    f"🛑 *Status:* {event_text}\n"
                    f"📊 *Score:* {score} ({overs})\n"
                )
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # --- EXTREME CASE 3: EARLY ALL-OUT & INNINGS BREAKS ---
        innings_transition = (cur_overs < last_over - 5)
        if innings_transition: last_over = 0.0 # Reset for the 2nd innings

        if not is_match_over:
            is_all_out = (wickets == "10")
            is_break = "innings break" in event_lower or is_all_out or innings_transition
            
            if is_break:
                eid = f"{m_id}_BREAK_{score}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    messages_to_send.append(
                        f"🛑 *INNINGS BREAK / ALL OUT: {match_name}*\n\n"
                        f"📊 *Innings Score:* {score} after {cur_overs} overs.\n"
                        f"🔗 [Live Score]({match_url})"
                    )
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

            # --- NORMAL 10-OVER LOGIC ---
            elif int(cur_overs // 10) > int(last_over // 10) and cur_overs >= 10:
                m_stone = int((cur_overs // 10) * 10)
                eid = f"{m_id}_O_{m_stone}_{score}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    messages_to_send.append(
                        f"🏏 *{m_stone} OVER UPDATE*\n\n"
                        f"*{match_name}*\n"
                        f"📊 *Score:* {score} after {cur_overs} overs.\n"
                        f"🔗 [Live Score]({match_url})"
                    )
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # --- PLAYER MILESTONES (50s / 100s) ---
        event_type = None
        if any(x in event_lower for x in ["fifty", "half-century", "half century", "50 runs", "reaches 50"]): 
            event_type = "50"
        elif any(x in event_lower for x in ["century", "hundred", "100 runs", "reaches 100"]): 
            event_type = "100"
        
        if event_type:
            eid = f"{m_id}_MILESTONE_{hash(event_text)}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                messages_to_send.append(
                    f"🔥 *PLAYER MILESTONE: {match_name}*\n\n"
                    f"⭐ Player reached a *{event_type}*!\n"
                    f"💬 _{event_text}_\n"
                    f"📊 *Score:* {score} ({overs})\n"
                )
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        cursor.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (m_id, cur_overs, toss_done))
        conn.commit()

        for msg in messages_to_send:
            send_telegram(msg)

    except Exception:
        pass

if __name__ == "__main__":
    print("🚀 Cricket Newsroom Worker Starting...")
    send_telegram("✅ *Bot Online!* Advanced safety layers initialized (All-outs, Rain delays, Early wins).")
    
    while True:
        try:
            handle_commands()
            matches = scrape_match_links()
            
            for match_name, match_link in matches:
                fetch_toss_update(match_link, match_name)
                fetch_match_update(match_link, match_name)
                
        except Exception as e:
            print("Loop Error:", e)
            
        time.sleep(25)
