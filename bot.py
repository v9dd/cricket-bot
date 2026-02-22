import requests
import os
import time
import sqlite3
import urllib.parse
from bs4 import BeautifulSoup
from datetime import datetime

# =====================
# CONFIGURATION
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # Ensure this is in your Railway/Environment variables

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

# =====================
# AI EDITOR (NARRATIVE STYLE)
# =====================
def get_pro_edit(text):
    if not GROQ_API_KEY: return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""You are a professional Cricket News Editor for a viral WhatsApp Channel.
Rewrite the raw match update into a short, crisp, narrative-style post. Do NOT use bullet points or lists. 

Follow this EXACT format and tone based on these examples:

Example 1:
🏏 TOSS UPDATE – ENG vs SL 🏏 
Sri Lanka have won the toss and elected to bowl first in their Super 8 opener at the Pallekele International Cricket Stadium.
A massive game in Group 2 to kick off the business end. Game on! 

Example 2:
🏏 10 OVER UPDATE – ENG vs SL 🏏 
England find themselves in a tough spot, reaching 68/4 after 10 overs.
The batting team is trying to build a fightback, but the bowlers have dominated the phase with crucial wickets.

Rules for your rewrite:
1. Create ONE clear heading with emojis (e.g., 🏏 [PHASE/EVENT] – [MATCH NAME] 🏏).
2. Write 1 or 2 short, punchy paragraphs summarizing the current state of the game. 
3. Weave the score, runs, and wickets smoothly into the sentences. DO NOT use rigid labels like "Score: X" or "Overs: Y".
4. Strictly NO bullet points. 
5. End with a short concluding hype sentence.

RAW UPDATE DATA to rewrite:
{text}
"""
    
    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5, 
        "max_tokens": 500
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=10)
        return res.json()['choices'][0]['message']['content']
    except Exception as e:
        print("AI Edit Error:", e)
        return None

# =====================
# CORE UTILITIES
# =====================
def send_telegram(text, pro_edit=False):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # 1. Send the instant raw template (Safety Net)
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": "true"}, timeout=10)
    except: pass

    # 2. If requested, fetch and send the AI version
    if pro_edit and GROQ_API_KEY:
        ai_text = get_pro_edit(text)
        if ai_text:
            try:
                requests.post(url, data={"chat_id": CHAT_ID, "text": f"✨ *PRO EDIT (COPY THIS):*\n\n{ai_text}", "parse_mode": "Markdown", "disable_web_page_preview": "true"}, timeout=10)
            except: pass

def get_img_link(query):
    safe_query = urllib.parse.quote(f"{query} Cricket Match {datetime.now().year}")
    return f"https://www.google.com/search?q={safe_query}&tbm=isch"

def is_intl(text):
    t = text.upper()
    if any(x in t for x in ["WOMEN", " U19", "TROPHY", "LEAGUE", " XI", "INDIA A", "PAKISTAN A"]): return False
    if any(f in t for f in ["TEST", "ODI", "T20I", "WORLD CUP"]): return True
    countries = ["INDIA", "AUSTRALIA", "ENGLAND", "NEW ZEALAND", "SOUTH AFRICA", "PAKISTAN", "SRI LANKA", "WEST INDIES", "BANGLADESH", "ZIMBABWE", "AFGHANISTAN", "IRELAND"]
    return sum(1 for c in countries if c in t) >= 2

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
                if is_intl(match_info):
                    todays_matches.append(f"• {match_info}")
        
        if not todays_matches:
            return "No international matches scheduled for today."
            
        header = f"📅 *TODAY'S INTERNATIONAL SCHEDULE*\n—————————————————\n_{datetime.now().strftime('%d %B %Y')}_\n\n"
        footer = f"\n\n🖼 [Tap for Series Graphics]({get_img_link('Cricket Schedule')})\n—————————————————\n🔔 *Keep notifications ON for live updates!*"
        return header + "\n".join(todays_matches) + footer
    except: return None

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
# TRACKING MANAGER & COMMANDS
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
            msg_data = update.get("message") or update.get("channel_post")
            if not msg_data: continue
            text = msg_data.get("text", "")

            if "/tracklist" in text:
                matches = scrape_match_links()
                if not matches:
                    send_telegram("📭 No international matches found to track.")
                    continue
                
                report = "📋 *TRACKING MANAGER*\n—————————————————\n"
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
                send_telegram("🏆 *LIVE & RECENT INTERNATIONALS* 🏆\n—————————————————\n" + "\n\n".join(summary_data))
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
        
        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return "Score not available yet"
        p = score_div.find_all("div")
        runs = p[0].get_text(strip=True)
        wickets = p[1].get_text(strip=True).replace("-", "")
        overs = p[2].get_text(strip=True).replace("(", "").replace(")", "")
        score_str = f"📊 {runs}-{wickets} ({overs} overs)"

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
        
        msg = f"🪙 *TOSS UPDATE* 🪙\n—————————————————\n🏆 *{match_name}*\n\n🏟 *{toss_text}*\n\n🖼 [Tap for Toss Photos]({get_img_link(match_name + ' Toss')})\n—————————————————\n🏏 _Match starting soon! Get ready!_"
        send_telegram(msg, pro_edit=True)
    except: pass

def fetch_match_update(match_url, match_name):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        
        score_div = soup.find("div", class_=lambda x: x and "text-3xl" in x and "font-bold" in x)
        if not score_div: return
        p = score_div.find_all("div")
        runs = p[0].get_text(strip=True).replace(",", "")
        wickets = int(p[1].get_text(strip=True).replace("-", "") or 0)
        overs_raw = p[2].get_text(strip=True).replace("(", "").replace(")", "")
        cur_overs = float(overs_raw or 0.0)
        score_display = f"{runs}/{wickets}"

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
        
        if cur_overs < last_ov - 5: 
            last_ov = 0.0
            last_wk = 0
            
        msg = None
        is_match_over = any(phrase in event_lower for phrase in ["won by", "win by", "match drawn", "match tied", "abandoned", "no result"])
        
        # 1. MATCH END
        if is_match_over:
            eid = f"{m_id}_MATCH_END"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🏆 *MATCH COMPLETED: FINAL RESULT* 🏆\n—————————————————\n🎯 *{event_text}*\n\n📊 *FINAL TALLY:*\n🔹 {match_name}\n🔹 Score: *{score_display}* ({overs_raw})\n\n🖼 [Tap for Winning Moments]({get_img_link(match_name)})\n—————————————————\n✅ *Follow us for more cricket updates!*"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # 2. INNINGS BREAK
        elif "innings break" in event_lower:
            eid = f"{m_id}_INNINGS_BREAK_{score_display}" 
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🛑 *INNINGS COMPLETED* 🛑\n—————————————————\n🏏 *{match_name}* finishes their innings.\n\n📊 *FINAL SCORE:* *{score_display}*\n🎯 *UPDATE:* _{event_text}_\n\n🖼 [Tap for Match Gallery]({get_img_link(match_name)})\n—————————————————\n🕒 _Second innings starts shortly. Who's winning this?_"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # 3. SMART OVER MILESTONES
        else:
            is_t20 = "T20" in match_name.upper()
            milestones = [6, 10, 15, 20] if is_t20 else [10, 20, 30, 40, 50, 60, 70, 80, 90]
            
            passed_m = None
            for m in milestones:
                if last_ov < m and cur_overs >= m:
                    passed_m = m
                    break
            
            if passed_m:
                eid = f"{m_id}_OV_{passed_m}_{runs}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    try: crr = f"{(int(runs) / cur_overs):.2f}"
                    except: crr = "N/A"
                    
                    phase_header = f"{passed_m}-OVER"
                    if is_t20 and passed_m == 6: phase_header = "POWERPLAY"
                    elif is_t20 and passed_m in [15, 20]: phase_header = "DEATH OVERS"
                    
                    msg = f"🏏 *{phase_header} UPDATE* 🏏\n—————————————————\n🏆 *{match_name}*\n\n📊 *SCORE:* *{score_display}*\n🕒 *OVERS:* {cur_overs}\n📈 *RUN RATE:* {crr}\n\n⚡ *LATEST:* _{event_text}_\n\n🖼 [Tap for Match Photos]({get_img_link(match_name)})\n—————————————————\n🔔 *Stay tuned for more live action!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # 4. PLAYER MILESTONES
        event_type = None
        if any(x in event_lower for x in ["fifty", "half-century", "half century", "50 runs", "reaches 50"]): 
            event_type = "50"
        elif any(x in event_lower for x in ["century", "hundred", "100 runs", "reaches 100"]): 
            event_type = "100"
        
        if event_type:
            eid = f"{m_id}_MILESTONE_{hash(event_text)}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🔥 *{event_type} REACHED!* 🔥\n—————————————————\n⭐ *Player Milestone*\n\n🏏 *MATCH:* {match_name}\n📊 *CURRENT SCORE:* *{score_display}* ({overs_raw})\n💬 *COMMENTARY:* _{event_text}_\n\n🖼 [Tap for Player Photos]({get_img_link(match_name + ' ' + event_text)})\n—————————————————\n👏 *A brilliant innings! Share the news!*"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # Fire notification with Pro Edit enabled!
        if msg: send_telegram(msg, pro_edit=True)
        
        cursor.execute("INSERT OR REPLACE INTO state VALUES (?,?,?,?)", (m_id, cur_overs, wickets, toss_done))
        conn.commit()
    except: pass

if __name__ == "__main__":
    print("🚀 WhatsApp Editor Bot + Groq Llama-3.3-70B Active!")
    send_telegram("✅ *Content Assistant Online!*\nSmart T20 Logic, Narrative AI Edits, and Image Fetching are fully ACTIVE.")
    while True:
        try:
            handle_commands()
            handle_daily_briefing()
            
            matches = scrape_match_links()
            for name, link in matches:
                m_id = link.split("/")[-2]
                
                # Check Tracking Config
                row = cursor.execute("SELECT is_active FROM tracking_config WHERE m_id=?", (m_id,)).fetchone()
                if row and row[0] == 0:
                    continue 
                
                fetch_toss_update(link, name)
                fetch_match_update(link, name)
                
        except Exception as e:
            print("Loop Error:", e)
        time.sleep(15)
