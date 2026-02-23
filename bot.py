import requests
import os
import time
import sqlite3
import urllib.parse
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import re

# =====================
# CONFIGURATION
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") 

if not BOT_TOKEN:
    print("🚨 SYSTEM HALTED: Missing Telegram Token!")
    time.sleep(60)
    exit()

HEADERS = {"User-Agent": "Mozilla/5.0"}
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    return datetime.now(IST)

# =====================
# DATABASE SETUP
# =====================
conn = sqlite3.connect("cricket_final.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, last_wickets INTEGER, toss_done INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS daily_logs (date TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS tracking_config (m_id TEXT PRIMARY KEY, match_name TEXT, is_active INTEGER DEFAULT 1)")

try:
    cursor.execute("ALTER TABLE state ADD COLUMN last_wicket_over REAL DEFAULT -10.0")
except:
    pass 
conn.commit()

match_state = {}
last_update_id = None

# =====================
# AI ENGINE
# =====================
def get_pro_edit(text: str, team_batting: str = None) -> str | None:
    if not GROQ_API_KEY or not text:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    clean_data = text.strip()[:400]
    context_hint = ""
    if team_batting:
        context_hint = (
            f"\nTEAM CONTEXT: {team_batting} is batting. "
            f"If wickets fall, frame it as pressure. "
            f"If scoring freely, frame it as dominance."
        )

    prompt = f"""You are a professional cricket news editor.
TASK: Convert the provided match update into a breaking news flash.

OUTPUT FORMAT STRICTLY:
• One catchy headline with emojis
• Exactly 2 short paragraphs
• Total 3–4 sentences maximum
• Double newline between paragraphs

STYLE:
• Dramatic, authoritative, fast-paced
• Professional sports journalism tone
• Natural integration of score, overs, wickets, and match situation
• No bullet points, no lists
• Do not invent "upsets" unless specifically stated in the data.

EXAMPLE OUTPUT:
🏏 COLLAPSE! – AUS vs IND 🏏
Australia’s batting unit has imploded under relentless pressure, crashing to 78/5 inside 14 overs.

India now smells blood, with momentum fully in their control as the match swings decisively.

{context_hint}
MATCH DATA: {clean_data}"""

    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are an elite cricket news editor."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 180,
        "top_p": 0.9
    }

    try:
        res = requests.post(url, headers=headers, json=data, timeout=15)
        res.raise_for_status()
        output = res.json()["choices"][0]["message"]["content"].strip()
        return output.replace("\n\n\n", "\n\n")
    except Exception as e:
        print(f"Groq API error: {e}")
        return None

# =====================
# CORE UTILITIES
# =====================
def send_telegram(text, pro_edit=False, team_batting=None):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": "true"}, timeout=10)
    except: pass

    if pro_edit and GROQ_API_KEY:
        ai_text = get_pro_edit(text, team_batting)
        if ai_text:
            try:
                requests.post(url, data={"chat_id": CHAT_ID, "text": f"✨ *PRO EDIT (COPY THIS):*\n\n{ai_text}", "parse_mode": "Markdown", "disable_web_page_preview": "true"}, timeout=10)
            except: pass

def get_img_link(query):
    safe_query = urllib.parse.quote(f"{query} Cricket Match {get_ist_now().year}")
    return f"https://www.google.com/search?q={safe_query}&tbm=isch"

def is_international_text_check(text):
    title = text.upper()
    if any(x in title for x in [" U19", "TROPHY", "LEAGUE", " XI", "INDIA A", "PAKISTAN A", "ENGLAND LIONS"]): return False
    intl_formats = ["TEST", "ODI", "T20I", "WORLD CUP"]
    if any(fmt in title for fmt in intl_formats): return True
    countries = ["INDIA", "AUSTRALIA", "ENGLAND", "NEW ZEALAND", "SOUTH AFRICA", "PAKISTAN", "SRI LANKA", "WEST INDIES", "BANGLADESH", "ZIMBABWE", "AFGHANISTAN", "IRELAND"]
    return sum(1 for c in countries if c in title) >= 2

# =====================
# DAILY BRIEFING FEATURE
# =====================
def scrape_todays_schedule():
    try:
        response = requests.get("https://www.cricbuzz.com/cricket-schedule", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        today_str = get_ist_now().strftime("%a %b %d").upper()
        todays_matches = []
        
        for block in soup.find_all("div", class_="cb-col-100 cb-col cb-schdl"):
            date_header = block.find("div", class_="cb-col-100 cb-col cb-lv-grn-strip")
            if not date_header or today_str not in date_header.get_text().upper(): continue
            match_list = block.find_next_sibling("div")
            if not match_list: continue
            
            for match in match_list.find_all("div", class_="cb-ovr-flo"):
                match_info = match.get_text(strip=True)
                if is_international_text_check(match_info):
                    todays_matches.append(f"• {match_info}")
        
        if not todays_matches: return "No international matches scheduled for today."
        header = f"📅 *TODAY'S INTERNATIONAL SCHEDULE*\n—————————————————\n_{get_ist_now().strftime('%d %B %Y')}_\n\n"
        footer = f"\n\n🖼 [Tap for Series Graphics]({get_img_link('Cricket Schedule')})\n—————————————————\n🔔 *Keep notifications ON for live updates!*"
        return header + "\n".join(todays_matches) + footer
    except: return None

def handle_daily_briefing():
    now = get_ist_now()
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
    if last_update_id: params["offset"] = last_update_id + 1
    
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
                else:
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
                else:
                    summary_data = []
                    for name, link in matches[:5]:
                        score = scrape_instant_score(link)
                        summary_data.append(f"🔹 *{name}*\n{score}")
                    send_telegram("🏆 *LIVE & RECENT INTERNATIONALS* 🏆\n—————————————————\n" + "\n\n".join(summary_data))
    except Exception as e:
        print("Command Error:", e)

# =====================
# SCRAPING ENGINE (BULLETPROOF)
# =====================
def scrape_match_links():
    try:
        res = requests.get("https://www.cricbuzz.com/cricket-match/live-scores", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        matches = []
        
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/live-cricket-scores/" in href:
                name = a_tag.get("title", "").strip()
                if not name:
                    name = a_tag.get_text(separator=" ", strip=True)
                
                if name and is_international_text_check(name):
                    full_link = "https://www.cricbuzz.com" + href if href.startswith("/") else href
                    if not any(full_link == m[1] for m in matches):
                        matches.append((name, full_link))
        return matches
    except Exception as e: 
        print("Scrape links error:", e)
        return []

def scrape_instant_score(match_url):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        score_div = soup.find("div", class_=lambda x: x and (("text-3xl" in x and "font-bold" in x) or "cb-font-20" in x))
        if not score_div: return "Score not available yet"
        
        p = score_div.find_all("div")
        if not p: return "Score structure unavailable"
        
        runs = p[0].get_text(strip=True)
        wickets = p[1].get_text(strip=True).replace("-", "") if len(p) > 1 else "0"
        overs = p[2].get_text(strip=True).replace("(", "").replace(")", "") if len(p) > 2 else ""
        score_str = f"📊 {runs}-{wickets} ({overs} overs)"

        event_text = ""
        status_div = soup.find("div", class_=lambda x: x and any(c in x for c in ["text-cb-danger", "text-cb-info", "text-cb-success"]))
        if status_div: event_text = status_div.get_text(strip=True)
        
        if any(phrase in event_text.lower() for phrase in ["won by", "win by", "match drawn", "match tied", "abandoned", "no result"]):
            return f"{score_str}\n🎯 *Result:* {event_text}"
        return f"{score_str}\n🔥 *Latest:* {event_text}" if event_text else score_str
    except: return "Error loading score"

def fetch_toss_update(match_url, match_name):
    if match_url not in match_state: match_state[match_url] = {"toss_sent": False}
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
        
        score_div = soup.find("div", class_=lambda x: x and (("text-3xl" in x and "font-bold" in x) or "cb-font-20" in x))
        if not score_div: return
        
        full_score_text = score_div.get_text(separator=" ", strip=True) 
        team_match = re.search(r'^([A-Za-z]+)', full_score_text)
        team_batting = team_match.group(1) if team_match else ""

        p = score_div.find_all("div")
        if not p: return
        
        runs_text = p[0].get_text(strip=True).replace(",", "")
        runs = int("".join(filter(str.isdigit, runs_text)) or 0)
        
        wickets = 0
        if len(p) > 1:
            w_text = p[1].get_text(strip=True).replace("-", "").replace("/", "")
            wickets = int(w_text) if w_text.isdigit() else 0
            
        overs_raw = ""
        if len(p) > 2:
            overs_raw = p[2].get_text(strip=True).replace("(", "").replace(")", "")
            
        cur_overs = float(overs_raw) if overs_raw.replace('.', '', 1).isdigit() else 0.0
        score_display = f"{team_batting} {runs}/{wickets}" if team_batting else f"{runs}/{wickets}"

        status_text = ""
        status_div = soup.find("div", class_=lambda x: x and any(c in x for c in ["text-cb-danger", "text-cb-info", "text-cb-success", "cb-text-complete", "cb-text-abandon"]))
        if status_div:
            status_text = status_div.get_text(strip=True)

        if not status_text:
            alt_status = soup.find(lambda tag: tag.name == "div" and tag.get("class") and any(phrase in tag.get_text(strip=True).lower() for phrase in ["won by", "abandoned", "target ", "innings break", "stumps", "no result"]))
            if alt_status and len(alt_status.get_text(strip=True)) < 100:
                 status_text = alt_status.get_text(strip=True)

        commentary_text = ""
        cm = soup.find("div", class_=lambda x: x and "leading-6" in x)
        if cm:
            eb = cm.find_all("div", recursive=False)
            if eb:
                t = eb[0] if "." in overs_raw else eb[-1]
                fl = t.find("div", class_=lambda x: x and "flex" in x and "gap-4" in x)
                if fl:
                    event_divs = fl.find_all("div", recursive=False)
                    if len(event_divs) >= 2: commentary_text = event_divs[1].get_text(strip=True)
                    
        event_text = status_text if status_text else commentary_text
        event_lower = event_text.lower()
        status_lower = status_text.lower()

        m_id = match_url.split("/")[-2] if "/" in match_url else str(hash(match_name))
        
        # FIX 1: Detect if this is a newly fetched old match to prevent startup spam
        is_new_match = False
        try:
            row = cursor.execute("SELECT last_over, last_wickets, toss_done, last_wicket_over FROM state WHERE m_id=?", (m_id,)).fetchone()
            if row:
                last_ov, last_wk, toss_done, last_wk_ov = row
            else:
                last_ov, last_wk, toss_done, last_wk_ov = (0.0, 0, 0, -10.0)
                is_new_match = True
        except:
            last_ov, last_wk, toss_done, last_wk_ov = (0.0, 0, 0, -10.0)
            is_new_match = True
        
        if cur_overs < last_ov - 5: 
            last_ov = 0.0
            last_wk = 0
            last_wk_ov = -10.0
            
        msg = None
        
        is_match_over = any(phrase in status_lower for phrase in ["won by", "win by", "drawn", "tied", "abandoned", "no result"])
        is_innings_break = (wickets == 10 and not is_match_over) or any(phrase in status_lower for phrase in ["innings break", "target", "stumps", "lunch", "tea"])
        
        # ---------------------------------------------------------------------------------
        # ANTI-SPAM SHIELD: If it's an old/finished match we just found, SILENTLY save it.
        # ---------------------------------------------------------------------------------
        if is_new_match and is_match_over:
            cursor.execute("INSERT OR IGNORE INTO events VALUES (?)", (f"{m_id}_MATCH_END",))
            cursor.execute("INSERT OR IGNORE INTO state (m_id, last_over, last_wickets, toss_done, last_wicket_over) VALUES (?,?,?,?,?)", (m_id, cur_overs, wickets, toss_done, last_wk_ov))
            conn.commit()
            return # Exit completely to avoid ANY spam

        # A. EARLY COLLAPSE & DOUBLE STRIKE (Protected against restart spam)
        if wickets > last_wk and not is_new_match:
            new_wk_ov = cur_overs
            if wickets == 3 and cur_overs <= 6.0 and last_wk < 3:
                eid = f"{m_id}_COLLAPSE_3WK"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    msg = f"🚨 *EARLY COLLAPSE* 🚨\n—————————————————\n💥 Huge trouble early on!\n\n🏏 *MATCH:* {match_name}\n📊 *SCORE:* *{score_display}* ({overs_raw})\n💬 *LATEST WICKET:* _{event_text}_\n\n🖼 [Tap for Match Action]({get_img_link(match_name)})\n—————————————————\n📉 *The batting side is under massive pressure!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))
            elif last_wk_ov > 0 and (new_wk_ov - last_wk_ov) <= 1.0 and wickets > 1:
                eid = f"{m_id}_DOUBLE_STRIKE_{wickets}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    msg = f"🔥 *DOUBLE STRIKE* 🔥\n—————————————————\n🎯 Two quick wickets have changed the momentum!\n\n🏏 *MATCH:* {match_name}\n📊 *NEW SCORE:* *{score_display}* ({overs_raw})\n💬 *LATEST:* _{event_text}_\n\n🖼 [Tap for Celebration Photos]({get_img_link(match_name)})\n—————————————————\n⚠️ *Huge turning point in the game!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))
            last_wk_ov = new_wk_ov 

        # B. MATCH END (Fixed ID to strictly prevent looping spam)
        if not msg and is_match_over:
            eid = f"{m_id}_MATCH_END"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🏆 *MATCH COMPLETED: FINAL RESULT* 🏆\n—————————————————\n🎯 *{status_text}*\n\n📊 *FINAL TALLY:*\n🔹 {match_name}\n🔹 Score: *{score_display}* ({overs_raw})\n\n🖼 [Tap for Winning Moments]({get_img_link(match_name)})\n—————————————————\n✅ *Follow us for more cricket updates!*"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # C. INNINGS BREAK
        elif not msg and is_innings_break:
            eid = f"{m_id}_INNINGS_BREAK_{runs}" 
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                msg = f"🛑 *INNINGS COMPLETED* 🛑\n—————————————————\n🏏 *{match_name}* finishes their innings.\n\n📊 *FINAL SCORE:* *{score_display}*\n🎯 *UPDATE:* _{status_text}_\n\n🖼 [Tap for Match Gallery]({get_img_link(match_name)})\n—————————————————\n🕒 _Second innings starts shortly. Who's winning this?_"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # D. SMART OVER MILESTONES
        elif not msg and not is_match_over:
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
                    try: crr = f"{(runs / cur_overs):.2f}"
                    except: crr = "N/A"
                    
                    phase_header = f"{passed_m}-OVER"
                    if is_t20 and passed_m == 6: phase_header = "POWERPLAY END"
                    elif is_t20 and passed_m in [15, 20]: phase_header = "DEATH OVERS"
                    
                    msg = f"🏏 *{phase_header} UPDATE* 🏏\n—————————————————\n🏆 *{match_name}*\n\n📊 *SCORE:* *{score_display}*\n🕒 *OVERS:* {cur_overs}\n📈 *RUN RATE:* {crr}\n\n⚡ *LATEST:* _{event_text}_\n\n🖼 [Tap for Match Photos]({get_img_link(match_name)})\n—————————————————\n🔔 *Stay tuned for more live action!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # E. PLAYER MILESTONES (With "New Match" Safety Shield)
        if not msg and not is_match_over and not is_new_match:
            event_type = None
            speed_alert = ""
            
            balls_faced = 999 
            ball_match = re.search(r'(\d+)\s*(balls|b)', event_lower)
            if ball_match:
                balls_faced = int(ball_match.group(1))

            if any(x in event_lower for x in ["fifty", "half-century", "half century", "50 runs", "reaches 50"]): 
                event_type = "50"
                if balls_faced <= 25: speed_alert = "⚡ EXPLOSIVE INNINGS ⚡\n"
            elif any(x in event_lower for x in ["century", "hundred", "100 runs", "reaches 100"]): 
                event_type = "100"
                if balls_faced <= 50: speed_alert = "⚡ SENSATIONAL CENTURY ⚡\n"
            
            if event_type:
                eid = f"{m_id}_MILESTONE_{hash(event_text)}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    header = f"🔥 *{event_type} REACHED!* 🔥"
                    if speed_alert: header = f"{speed_alert}{header}"
                    
                    msg = f"{header}\n—————————————————\n⭐ *Player Milestone*\n\n🏏 *MATCH:* {match_name}\n📊 *CURRENT SCORE:* *{score_display}* ({overs_raw})\n💬 *COMMENTARY:* _{event_text}_\n\n🖼 [Tap for Player Photos]({get_img_link(match_name + ' ' + event_text)})\n—————————————————\n👏 *What a knock! Share the news!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # F. SEND MESSAGE
        if msg: 
            send_telegram(msg, pro_edit=True, team_batting=team_batting)
        
        try:
            cursor.execute("INSERT OR REPLACE INTO state (m_id, last_over, last_wickets, toss_done, last_wicket_over) VALUES (?,?,?,?,?)", (m_id, cur_overs, wickets, toss_done, last_wk_ov))
        except:
            cursor.execute("INSERT OR REPLACE INTO state (m_id, last_over, last_wickets, toss_done) VALUES (?,?,?,?)", (m_id, cur_overs, wickets, toss_done))
            
        conn.commit()
    except Exception as e:
        print("Scrape Error:", e)

if __name__ == "__main__":
    print("🚀 WhatsApp Content Assistant & Narrative AI Engine Starting...")
    send_telegram("✅ *Content Assistant Online!*\n- SPAM SHIELD Active 🛡️\n- Duplicate Blocks Fixed 🔒\n- Token Sinks Plugged ⚡")
    
    while True:
        try:
            handle_commands()
            handle_daily_briefing() 
            
            matches = scrape_match_links()
            for name, link in matches:
                m_id = link.split("/")[-2]
                
                row = cursor.execute("SELECT is_active FROM tracking_config WHERE m_id=?", (m_id,)).fetchone()
                if row and row[0] == 0:
                    continue 
                
                fetch_toss_update(link, name)
                fetch_match_update(link, name)
                
        except Exception as e:
            print("Main Loop Error:", e)
        
        time.sleep(15)
