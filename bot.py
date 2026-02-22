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

HEADERS = {"User-Agent": "Mozilla/5.0"}

conn = sqlite3.connect("cricket_final.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, last_wickets INTEGER, toss_done INTEGER DEFAULT 0)")
conn.commit()

match_state = {}

def send_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": "true"}, timeout=10)
    except: pass

def handle_commands():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url, params={"timeout": 5}, timeout=10).json()
        if not res.get("ok"): return
        
        # We handle incoming commands instantly
        for update in res.get("result", []):
            # Acknowledge the update so Telegram stops sending it
            requests.get(url, params={"offset": update["update_id"] + 1}, timeout=5)
            
            msg_data = update.get("message") or update.get("channel_post")
            if not msg_data: continue
            
            if "/score" in msg_data.get("text", ""):
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
    except: pass

# =====================
# THE NEW "SMART" INTERNATIONAL FILTER
# =====================
def scrape_match_links():
    try:
        res = requests.get("https://www.cricbuzz.com/cricket-match/live-scores", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        main = soup.find("div", class_="flex flex-col gap-2")
        matches = []
        if not main: return matches
        
        # Cricbuzz groups matches into blocks. We ONLY read blocks labeled "International" or "ICC"
        for block in main.find_all("div", recursive=False):
            block_text = block.get_text(separator=" ", strip=True).upper()
            
            # This completely eliminates the need for a list of countries
            if not block_text.startswith("INTERNATIONAL") and not block_text.startswith("ICC"):
                continue
                
            for card in block.select("a.w-full.bg-cbWhite"):
                name = card.get("title", "").strip()
                if not name: continue
                
                # Double safety: Exclude Women and U19 just in case they are in the folder
                if "WOMEN" in name.upper() or " U19" in name.upper():
                    continue
                    
                matches.append((name, "https://www.cricbuzz.com" + card["href"]))
        return matches
    except: return []

def scrape_instant_score(match_url):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return "Score not available yet"
        
        p = score_div.find_all("div")
        runs = p[0].get_text(strip=True)
        wickets = p[1].get_text(strip=True).replace("-", "")
        overs = p[2].get_text(strip=True).replace("(", "").replace(")", "")
        return f"{runs}-{wickets} ({overs} overs)"
    except: return "Error loading score"

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
    except: pass

def fetch_match_update(match_url, match_name):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 1. SCRAPE CORE STATS
        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return
        p = score_div.find_all("div")
        runs = p[0].get_text(strip=True)
        wickets = int(p[1].get_text(strip=True).replace("-", "") or 0)
        overs_raw = p[2].get_text(strip=True).replace("(", "").replace(")", "")
        cur_overs = float(overs_raw or 0.0)
        score_display = f"{runs}-{wickets}"

        # 2. LATEST EVENT TEXT
        commentary_main = soup.find("div", class_=lambda x: x and "leading-6" in x)
        event_text = ""
        if commentary_main:
            event_blocks = commentary_main.find_all("div", recursive=False)
            if event_blocks:
                target_block = event_blocks[0] if "." in overs_raw else (event_blocks[1] if len(event_blocks) > 1 else event_blocks[0])
                flex_row = target_block.find("div", class_=lambda x: x and "flex" in x and "gap-4" in x)
                if flex_row:
                    event_divs = flex_row.find_all("div", recursive=False)
                    if len(event_divs) >= 2:
                        event_text = event_divs[1].get_text(strip=True)

        event_lower = event_text.lower()

        # 3. LOAD STATE
        m_id = match_url.split("/")[-2] if "/" in match_url else str(hash(match_name))
        row = cursor.execute("SELECT last_over, last_wickets, toss_done FROM state WHERE m_id=?", (m_id,)).fetchone()
        last_ov, last_wk, toss_done = row if row else (0.0, 0, 0)
        
        # Detect Innings change (Reset math logic safely)
        if cur_overs < last_ov - 5:
            last_ov = 0.0
            
        msg = None
        
        # 4. TRIGGERS
        
        # A. MATCH END
        is_match_over = any(phrase in event_lower for phrase in ["won by", "win by", "match drawn", "match tied", "abandoned", "no result"])
        if is_match_over:
            eid = f"{m_id}_MATCH_END"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🏆 *MATCH COMPLETED*\n\n*{match_name}*\n🎯 {event_text}\n📊 Final Score: {score_display} ({overs_raw})\n\n🔗 [Live Score]({match_url})"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # B. INNINGS BREAK (Strict Official Text Only - Stops fake drops)
        elif "innings break" in event_lower:
            eid = f"{m_id}_INNINGS_BREAK_{score_display}" 
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🛑 *INNINGS BREAK*\n\n*{match_name}*\n📊 Score: {score_display} ({overs_raw})\n\n🔗 [Live Score]({match_url})"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # C. 10 OVER MILESTONES
        elif int(cur_overs // 10) > int(last_ov // 10) and cur_overs >= 10:
            m_stone = int((cur_overs // 10) * 10)
            eid = f"{m_id}_OV_{m_stone}_{runs}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🏏 *{m_stone} OVER UPDATE*\n\n*{match_name}*\n📊 Score: {score_display} after {cur_overs} overs.\n\n🔗 [Live Score]({match_url})"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # D. PLAYER MILESTONES (50s / 100s)
        event_type = None
        if any(x in event_lower for x in ["fifty", "half-century", "half century", "50 runs", "reaches 50"]): 
            event_type = "50"
        elif any(x in event_lower for x in ["century", "hundred", "100 runs", "reaches 100"]): 
            event_type = "100"
        
        if event_type:
            eid = f"{m_id}_MILESTONE_{hash(event_text)}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🔥 *PLAYER MILESTONE: {match_name}*\n\n⭐ Player reached a *{event_type}*!\n💬 _{event_text}_\n📊 Score: {score_display} ({overs_raw})\n\n🔗 [Live Score]({match_url})"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        if msg: send_telegram(msg)

        # SAVE NEW STATE
        cursor.execute("INSERT OR REPLACE INTO state VALUES (?,?,?,?)", (m_id, cur_overs, wickets, toss_done))
        conn.commit()

    except Exception as e:
        pass

if __name__ == "__main__":
    print("🚀 Pro-Tier Cricket Bot Starting...")
    send_telegram("✅ *Bot Online!* Running on Advanced Category Filters & 15-second polling.")
    while True:
        try:
            handle_commands()
            matches = scrape_match_links()
            for name, link in matches:
                fetch_toss_update(link, name)
                fetch_match_update(link, name)
        except Exception as e:
            print("Loop Error:", e)
            
        # Reduced to 15 seconds to ensure blazing fast 10-over updates
        time.sleep(15)
