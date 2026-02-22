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

# =====================
# DATABASE SETUP
# =====================
conn = sqlite3.connect("cricket_final.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, last_wickets INTEGER, toss_done INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS daily_logs (date TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS tracking_config (m_id TEXT PRIMARY KEY, match_name TEXT, is_active INTEGER DEFAULT 1)")
conn.commit()

match_state = {}
last_update_id = None

def send_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": "true"}, timeout=10)
    except: pass

# =====================
# DAILY BRIEFING FEATURE
# =====================
def scrape_todays_schedule():
    url = "https://www.cricbuzz.com/cricket-schedule"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        today_str = datetime.now().strftime("%a %b %d").upper()
        
        schedule_blocks = soup.find_all("div", class_="cb-col-100 cb-col cb-schdl")
        todays_matches = []
        
        for block in schedule_blocks:
            date_header = block.find("div", class_="cb-col-100 cb-col cb-lv-grn-strip")
            if not date_header or today_str not in date_header.get_text().upper():
                continue
            
            match_list = block.find_next_sibling("div")
            if not match_list: continue
            
            for match in match_list.find_all("div", class_="cb-ovr-flo"):
                match_info = match.get_text(strip=True)
                if is_international_text_check(match_info):
                    todays_matches.append(f"• {match_info}")
        
        if not todays_matches:
            return "No international matches scheduled for today."
            
        header = f"📅 *TODAY'S INTERNATIONAL SCHEDULE*\n_{datetime.now().strftime('%d %B %Y')}_\n\n"
        return header + "\n".join(todays_matches)
    except: return None

def is_international_text_check(text):
    title = text.upper()
    if any(x in title for x in ["WOMEN", " U19", "TROPHY", "LEAGUE"]): return False
    intl_formats = ["TEST", "ODI", "T20I", "WORLD CUP"]
    if any(fmt in title for fmt in intl_formats): return True
    countries = ["INDIA", "AUSTRALIA", "ENGLAND", "NEW ZEALAND", "SOUTH AFRICA", "PAKISTAN", "SRI LANKA", "WEST INDIES", "BANGLADESH", "ZIMBABWE", "AFGHANISTAN", "IRELAND"]
    if sum(1 for c in countries if c in title) >= 2: return True
    return False

def handle_daily_briefing():
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    if now.hour == 8:
        row = cursor.execute("SELECT date FROM daily_logs WHERE date=?", (today_date,)).fetchone()
        if not row:
            brief = scrape_todays_schedule()
            if brief:
                send_telegram(brief)
                cursor.execute("INSERT INTO daily_logs (date) VALUES (?)", (today_date,))
                conn.commit()

# =====================
# COMMAND HANDLER
# =====================
def handle_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    # ENHANCEMENT: Fixed the offset logic so Telegram stops spamming past commands
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

            if "/tracklist" in text:
                matches = scrape_match_links()
                if not matches:
                    send_telegram("📭 No international matches found to track.")
                    continue
                
                report = "📋 *TRACKING MANAGER*\n\n"
                for i, (name, link) in enumerate(matches):
                    m_id = link.split("/")[-2]
                    row = cursor.execute("SELECT is_active FROM tracking_config WHERE m_id=?", (m_id,)).fetchone()
                    status = "✅ Tracking" if (not row or row[0] == 1) else "❌ Muted"
                    report += f"*{i+1}.* {name}\nStatus: {status}\nToggle: `/track {i+1}` or `/stop {i+1}`\n\n"
                send_telegram(report)

            elif "/track" in text:
                try:
                    idx = int(text.split()[-1]) - 1
                    matches = scrape_match_links()
                    name, link = matches[idx]
                    m_id = link.split("/")[-2]
                    cursor.execute("INSERT OR REPLACE INTO tracking_config VALUES (?, ?, 1)", (m_id, name))
                    conn.commit()
                    send_telegram(f"✅ Now tracking: *{name}*")
                except: send_telegram("⚠️ Invalid ID. Use `/tracklist` to see IDs.")

            elif "/stop" in text:
                try:
                    idx = int(text.split()[-1]) - 1
                    matches = scrape_match_links()
                    name, link = matches[idx]
                    m_id = link.split("/")[-2]
                    cursor.execute("INSERT OR REPLACE INTO tracking_config VALUES (?, ?, 0)", (m_id, name))
                    conn.commit()
                    send_telegram(f"❌ Muted: *{name}*")
                except: send_telegram("⚠️ Invalid ID. Use `/tracklist` to see IDs.")

            elif "/score" in text:
                send_telegram("🏏 *Fetching live & completed matches...*")
                matches = scrape_match_links()
                if not matches:
                    send_telegram("⚠️ There are no international matches on the board right now.")
                    continue
                
                summary_data = []
                for name, link in matches[:5]:
                    score = scrape_instant_score(link)
                    summary_data.append(f"🔹 *{name}*\n{score}")
                send_telegram("🏆 *LIVE & RECENT INTERNATIONALS* 🏆\n\n" + "\n\n".join(summary_data))
    except: pass

# =====================
# SCRAPING ENGINE 
# =====================
def scrape_match_links():
    try:
        res = requests.get("https://www.cricbuzz.com/cricket-match/live-scores", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        main = soup.find("div", class_="flex flex-col gap-2")
        matches = []
        if not main: return matches
        
        for block in main.find_all("div", recursive=False):
            block_text = block.get_text(separator=" ", strip=True).upper()
            if not block_text.startswith("INTERNATIONAL") and not block_text.startswith("ICC"):
                continue
            for card in block.select("a.w-full.bg-cbWhite"):
                name = card.get("title", "").strip()
                if not name or "WOMEN" in name.upper() or " U19" in name.upper():
                    continue
                matches.append((name, "https://www.cricbuzz.com" + card["href"]))
        return matches
    except: return []

def scrape_instant_score(match_url):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Get Score
        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return "Score not available yet"
        p = score_div.find_all("div")
        runs = p[0].get_text(strip=True)
        wickets = p[1].get_text(strip=True).replace("-", "")
        overs = p[2].get_text(strip=True).replace("(", "").replace(")", "")
        score_str = f"📊 {runs}-{wickets} ({overs} overs)"

        # ENHANCEMENT: Get Result or Latest Event for /score
        event_text = ""
        commentary_main = soup.find("div", class_=lambda x: x and "leading-6" in x)
        if commentary_main:
            event_blocks = commentary_main.find_all("div", recursive=False)
            if event_blocks:
                target_block = event_blocks[0] if "." in overs else (event_blocks[1] if len(event_blocks) > 1 else event_blocks[0])
                flex_row = target_block.find("div", class_=lambda x: x and "flex" in x and "gap-4" in x)
                if flex_row:
                    event_divs = flex_row.find_all("div", recursive=False)
                    if len(event_divs) >= 2:
                        event_text = event_divs[1].get_text(strip=True)

        if any(phrase in event_text.lower() for phrase in ["won by", "win by", "match drawn", "match tied", "abandoned", "no result"]):
            return f"{score_str}\n🎯 *Result:* {event_text}"
        
        return f"{score_str}\n🔥 *Latest:* {event_text}" if event_text else score_str
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
        
        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return
        p = score_div.find_all("div")
        runs = p[0].get_text(strip=True)
        wickets = int(p[1].get_text(strip=True).replace("-", "") or 0)
        overs_raw = p[2].get_text(strip=True).replace("(", "").replace(")", "")
        cur_overs = float(overs_raw or 0.0)
        score_display = f"{runs}-{wickets}"

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

        m_id = match_url.split("/")[-2] if "/" in match_url else str(hash(match_name))
        row = cursor.execute("SELECT last_over, last_wickets, toss_done FROM state WHERE m_id=?", (m_id,)).fetchone()
        last_ov, last_wk, toss_done = row if row else (0.0, 0, 0)
        
        # ENHANCEMENT: Reset both overs AND wickets for 2nd Innings
        if cur_overs < last_ov - 5: 
            last_ov = 0.0
            last_wk = 0
            
        msg = None
        is_match_over = any(phrase in event_lower for phrase in ["won by", "win by", "match drawn", "match tied", "abandoned", "no result"])
        
        if is_match_over:
            eid = f"{m_id}_MATCH_END"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🏆 *MATCH COMPLETED*\n\n*{match_name}*\n🎯 {event_text}\n📊 Final Score: {score_display} ({overs_raw})\n\n🔗 [Live Score]({match_url})"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        elif "innings break" in event_lower:
            eid = f"{m_id}_INNINGS_BREAK_{score_display}" 
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🛑 *INNINGS BREAK*\n\n*{match_name}*\n📊 Score: {score_display} ({overs_raw})\n\n🔗 [Live Score]({match_url})"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        elif int(cur_overs // 10) > int(last_ov // 10) and cur_overs >= 10:
            m_stone = int((cur_overs // 10) * 10)
            eid = f"{m_id}_OV_{m_stone}_{runs}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🏏 *{m_stone} OVER UPDATE*\n\n*{match_name}*\n📊 Score: {score_display} after {cur_overs} overs.\n\n🔗 [Live Score]({match_url})"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

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
        cursor.execute("INSERT OR REPLACE INTO state VALUES (?,?,?,?)", (m_id, cur_overs, wickets, toss_done))
        conn.commit()
    except: pass

if __name__ == "__main__":
    print("🚀 Pro-Tier Cricket Bot Starting...")
    send_telegram("✅ *Bot Online!* Tracking Manager & Match Results system are fully active.")
    while True:
        try:
            handle_commands()
            handle_daily_briefing()
            
            matches = scrape_match_links()
            for name, link in matches:
                m_id = link.split("/")[-2]
                
                # Check Tracking Status: skip if muted (0)
                row = cursor.execute("SELECT is_active FROM tracking_config WHERE m_id=?", (m_id,)).fetchone()
                if row and row[0] == 0:
                    continue 
                
                fetch_toss_update(link, name)
                fetch_match_update(link, name)
                
        except Exception as e:
            print("Loop Error:", e)
        time.sleep(15)
