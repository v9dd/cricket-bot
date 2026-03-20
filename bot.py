import hashlib
import logging
import os
import re
import sqlite3
import time
import urllib.parse
import traceback
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

# =====================
# CONFIGURATION
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

HEADERS = {"User-Agent": "Mozilla/5.0"}
IST = timezone(timedelta(hours=5, minutes=30))
RESULT_PHRASES = ["won by", "win by", "match drawn", "match tied", "abandoned", "no result"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def get_ist_now():
    return datetime.now(IST)

# =====================
# DATABASE SETUP
# =====================
try:
    conn = sqlite3.connect("cricket_final.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, last_wickets INTEGER, toss_done INTEGER DEFAULT 0, innings INTEGER DEFAULT 1)"
    )
    cursor.execute("CREATE TABLE IF NOT EXISTS daily_logs (date TEXT PRIMARY KEY)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS tracking_config (m_id TEXT PRIMARY KEY, match_name TEXT, is_active INTEGER DEFAULT 1)"
    )

    # FIX: Isolate ALTER TABLE statements so one existing column doesn't break the others
    try: cursor.execute("ALTER TABLE state ADD COLUMN last_wicket_over REAL DEFAULT -10.0")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE state ADD COLUMN innings INTEGER DEFAULT 1")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE state ADD COLUMN last_double_strike_wk INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    
    conn.commit()
except Exception as e:
    logger.error(f"Database Initialization Error: {e}")

match_state = {}
last_update_id = None

# =====================
# AI ENGINE
# =====================
def get_pro_edit(match_facts):
    if not GROQ_API_KEY or not match_facts:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    # Restoring the "Flavor" with examples while maintaining "Fact Integrity"
    prompt = f"""You are a professional Cricket News Editor for a premium WhatsApp channel.
Rewrite the raw match data into a CRISP NARRATIVE post.

YOUR OUTPUT MUST MIRROR THE TONE AND STRUCTURE OF THESE EXAMPLES:

EXAMPLE 1 (Toss):
🏏 TOSS UPDATE – ENG vs SL 🏏
Sri Lanka have won the toss and elected to bowl first in their Super 8 opener at the Pallekele International Cricket Stadium.

A massive game in Group 2 to kick off the business end. The Lankan Lions will look to exploit the early moisture on a surface that promises plenty of turn. Game on!

EXAMPLE 2 (Match Update):
🏏 10 OVER UPDATE – ENG vs SL 🏏
England find themselves in a tough spot, reaching 68/4 after 10 overs in their Super 8 opener.

Phil Salt (37*) is leading a lone fightback, but Sri Lanka's spinners have dominated, including the massive wicket of captain Harry Brook (14) right at the 10-over mark. The middle order needs to stabilize quickly or risk a complete collapse.

---
STRICT CURRENT FACTS TO USE:
- Match: {match_facts.get('match_name', 'Unknown')}
- Event: {match_facts.get('event_type', 'LIVE UPDATE')}
- Batting Team: {match_facts.get('team_batting', 'Unknown')}
- Bowling Team: {match_facts.get('team_bowling', 'Unknown')}
- Current Innings: {match_facts.get('innings', 1)}
- Score: {match_facts.get('score_display', 'Unknown')}
- Official Status: {match_facts.get('status_text', '')}

RULES:
1. Exactly 1 Heading and 2 narrative paragraphs.
2. IMPORTANT: Use a double newline (\n\n) between paragraphs.
3. Total Length: 3-4 sentences.
4. STRICT: If 'Event' is MATCH_END, the post must celebrate the winner from the 'Official Status'. 
5. STRICT: If 'Current Innings' is 2, DO NOT mention who won the toss in your summary. Focus ONLY on the chase.
6. NEVER invent stats not provided in the 'STRICT CURRENT FACTS' above.
"""

    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are an elite cricket news editor who mirror's the user's specific writing style examples perfectly."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5, # Slightly tightened to respect the new Innings rule
        "max_tokens": 145,
        "top_p": 0.9,
    }

    try:
        res = requests.post(url, headers=headers, json=data, timeout=15)
        res.raise_for_status()
        output = res.json()["choices"][0]["message"]["content"].strip()
        return output.replace("\n\n\n", "\n\n")
    except Exception as e:
        logger.warning("Groq API error: %s", e)
        return None

# =====================
# CORE UTILITIES
# =====================
def send_telegram(raw_text, pro_edit=False, match_facts=None):
    if not raw_text or not BOT_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # 1. SEND RAW TEXT FIRST
    try:
        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": raw_text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": "true",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("send_telegram raw failed: %s", exc)

    # 2. SEND AI VERSION SECOND (Without "PRO EDIT" label)
    if pro_edit and GROQ_API_KEY and match_facts:
        ai_text = get_pro_edit(match_facts)
        if ai_text:
            try:
                requests.post(
                    url,
                    data={
                        "chat_id": CHAT_ID,
                        "text": ai_text, 
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": "true",
                    },
                    timeout=10,
                )
            except requests.RequestException as exc:
                logger.warning("send_telegram AI failed: %s", exc)

def get_img_link(query):
    safe_query = urllib.parse.quote(f"{query} Cricket Match {get_ist_now().year}")
    return f"https://www.google.com/search?q={safe_query}&tbm=isch"

def overs_to_balls(overs):
    if not overs:
        return 0
    m = re.match(r"^(\d+)(?:\.(\d))?$", overs.strip())
    if not m:
        return 0
    whole = int(m.group(1))
    balls = int(m.group(2) or 0)
    balls = min(max(balls, 0), 5)
    return whole * 6 + balls

def stable_event_suffix(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]

def is_international_text_check(text):
    title = text.upper()
    if any(x in title for x in [" U19", "TROPHY", "LEAGUE", " XI", "INDIA A", "PAKISTAN A", "ENGLAND LIONS", "HONG KONG", "CHINA"]):
        return False
    
    countries = [
        "INDIA", "AUSTRALIA", "ENGLAND", "NEW ZEALAND", "SOUTH AFRICA",
        "PAKISTAN", "SRI LANKA", "WEST INDIES", "BANGLADESH", "ZIMBABWE",
        "AFGHANISTAN", "IRELAND"
    ]
    return sum(1 for c in countries if c in title) >= 2

def is_result_text(text):
    lower = (text or "").lower()
    return any(phrase in lower for phrase in RESULT_PHRASES)

def is_womens_match(match_name):
    # Detects if a match is a women's game to auto-mute it
    name_up = match_name.upper()
    return "WOMEN" in name_up or " W " in name_up or name_up.endswith(" W")

# =====================
# DAILY BRIEFING FEATURE
# =====================
def scrape_todays_schedule():
    try:
        response = requests.get(
            "https://www.cricbuzz.com/cricket-schedule", headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(response.text, "html.parser")
        today_str = get_ist_now().strftime("%a %b %d").upper()
        todays_matches = []

        for block in soup.find_all("div", class_="cb-col-100 cb-col cb-schdl"):
            date_header = block.find("div", class_="cb-col-100 cb-col cb-lv-grn-strip")
            if not date_header or today_str not in date_header.get_text().upper():
                continue
            match_list = block.find_next_sibling("div")
            if not match_list:
                continue

            for match in match_list.find_all("div", class_="cb-ovr-flo"):
                match_info = match.get_text(strip=True)
                if is_international_text_check(match_info):
                    todays_matches.append(f"• {match_info}")

        if not todays_matches:
            return "No major international matches scheduled for today."
        header = f"📅 *TODAY'S INTERNATIONAL SCHEDULE*\n—————————————————\n_{get_ist_now().strftime('%d %B %Y')}_\n\n"
        footer = "\n\n🖼 [Tap for Series Graphics]({})\n—————————————————\n🔔 *Keep notifications ON for live updates!*".format(
            get_img_link("Cricket Schedule")
        )
        return header + "\n".join(todays_matches) + footer
    except Exception as exc:
        logger.warning("Schedule scrape failed: %s", exc)
        return None

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
def _command_matches(text, command):
    return text.strip().startswith(command)

def handle_commands():
    global last_update_id
    if not BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 5}
    if last_update_id is not None:
        params["offset"] = last_update_id + 1

    try:
        res = requests.get(url, params=params, timeout=10).json()
        if not res.get("ok"):
            return

        for update in res.get("result", []):
            last_update_id = update["update_id"]
            msg_data = update.get("message") or update.get("channel_post")
            if not msg_data:
                continue
            text = msg_data.get("text", "")

            if _command_matches(text, "/tracklist"):
                matches = scrape_match_links()
                if not matches:
                    send_telegram("📭 No LIVE international matches found right now.")
                else:
                    report = "📋 *TRACKING MANAGER*\n—————————————————\n"
                    for i, (name, link) in enumerate(matches):
                        m_id = link.split("/")[-2]
                        row = cursor.execute(
                            "SELECT is_active FROM tracking_config WHERE m_id=?", (m_id,)
                        ).fetchone()
                        
                        # Apply Women's default mute logic
                        default_active = 0 if is_womens_match(name) else 1
                        is_active = row[0] if row else default_active
                        
                        status = "✅ Tracking" if is_active == 1 else "❌ Muted"
                        report += f"*{i + 1}.* {name}\nStatus: {status}\nToggle: `/track {i + 1}` or `/stop {i + 1}`\n\n"
                    send_telegram(report)

            elif _command_matches(text, "/track"):
                try:
                    idx = int(text.split()[-1]) - 1
                    matches = scrape_match_links()
                    name, link = matches[idx]
                    m_id = link.split("/")[-2]
                    cursor.execute(
                        "INSERT OR REPLACE INTO tracking_config VALUES (?, ?, 1)",
                        (m_id, name),
                    )
                    conn.commit()
                    send_telegram(f"✅ Now tracking: *{name}*")
                except (ValueError, IndexError):
                    send_telegram("⚠️ Invalid ID. Use /tracklist to see active match numbers.")

            elif _command_matches(text, "/stop"):
                try:
                    idx = int(text.split()[-1]) - 1
                    matches = scrape_match_links()
                    name, link = matches[idx]
                    m_id = link.split("/")[-2]
                    cursor.execute(
                        "INSERT OR REPLACE INTO tracking_config VALUES (?, ?, 0)",
                        (m_id, name),
                    )
                    conn.commit()
                    send_telegram(f"❌ Successfully Muted: *{name}*")
                except (ValueError, IndexError):
                    send_telegram("⚠️ Invalid ID. Use /tracklist to see active match numbers.")

            elif _command_matches(text, "/score"):
                send_telegram("🏏 *Fetching live matches...*")
                matches = scrape_match_links()
                if not matches:
                    send_telegram(
                        "⚠️ There are no international matches on the board right now."
                    )
                else:
                    summary_data = []
                    for name, link in matches[:5]:
                        score = scrape_instant_score(link)
                        summary_data.append(f"🔹 *{name}*\n{score}")
                    send_telegram(
                        "🏆 *LIVE INTERNATIONALS* 🏆\n—————————————————\n"
                        + "\n\n".join(summary_data)
                    )
    except Exception as e:
        logger.warning("Command Error: %s", e)

# =====================
# SCRAPING ENGINE
# =====================
def scrape_match_links():
    try:
        res = requests.get(
            "https://www.cricbuzz.com/cricket-match/live-scores",
            headers=HEADERS,
            timeout=15,
        )
        soup = BeautifulSoup(res.text, "html.parser")
        matches = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            
            # Allow /cricket-scores/ so we don't drop matches the second they finish
            if "/live-cricket-scores/" not in href and "/cricket-scores/" not in href:
                continue

            name = a_tag.get("title", "").strip() or a_tag.get_text(
                separator=" ", strip=True
            )
            if not name or not is_international_text_check(name):
                continue

            full_link = "https://www.cricbuzz.com" + href if href.startswith("/") else href
            if not any(full_link == m[1] for m in matches):
                matches.append((name, full_link))
        return matches
    except Exception as e:
        logger.warning("match links scrape failed: %s", e)
        return []

def scrape_instant_score(match_url):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        score_div = soup.find(
            "div",
            class_=lambda x: x and (("text-3xl" in x and "font-bold" in x) or "cb-font-20" in x),
        )
        if not score_div:
            return "Score not available yet"

        p = score_div.find_all("div")
        if not p:
            return "Score structure unavailable"

        runs = p[0].get_text(strip=True)
        wickets = p[1].get_text(strip=True).replace("-", "") if len(p) > 1 else "0"
        overs = (
            p[2].get_text(strip=True).replace("(", "").replace(")", "")
            if len(p) > 2
            else ""
        )
        score_str = f"📊 {runs}-{wickets} ({overs} overs)"

        event_text = ""
        status_div = soup.find(
            "div",
            class_=lambda x: x
            and any(c in x for c in ["text-cb-danger", "text-cb-info", "text-cb-success"]),
        )
        if status_div:
            event_text = status_div.get_text(strip=True)

        if is_result_text(event_text):
            return f"{score_str}\n🎯 *Result:* {event_text}"
        return f"{score_str}\n🔥 *Latest:* {event_text}" if event_text else score_str
    except Exception as exc:
        logger.warning("instant score failed for %s: %s", match_url, exc)
        return "Error loading score"

def fetch_toss_update(match_url, match_name):
    if match_url not in match_state:
        match_state[match_url] = {"toss_sent": False}
    if match_state[match_url]["toss_sent"]:
        return

    scorecard_url = match_url.replace("live-cricket-scores", "live-cricket-scorecard").replace("cricket-scores", "live-cricket-scorecard").replace("www.cricbuzz.com", "m.cricbuzz.com")
    
    try:
        response = requests.get(scorecard_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return
        soup = BeautifulSoup(response.text, "html.parser")
        toss_label = soup.find(
            lambda tag: tag.name == "div"
            and "font-bold" in tag.get("class", [])
            and "Toss" in tag.get_text()
        )
        if not toss_label:
            return
        toss_text = toss_label.find_next("div").get_text(strip=True)
        match_state[match_url]["toss_sent"] = True

        msg = f"🪙 *TOSS UPDATE* 🪙\n—————————————————\n🏆 *{match_name}*\n\n🏟 *{toss_text}*\n\n🖼 [Tap for Toss Photos]({get_img_link(match_name + ' Toss')})\n—————————————————\n🏏 _Match starting soon! Get ready!_"
        
        mf = {"match_name": match_name, "event_type": "TOSS", "status_text": toss_text, "innings": 1}
        send_telegram(msg, pro_edit=True, match_facts=mf)
    except Exception as exc:
        logger.warning("fetch_toss_update failed: %s", exc)

def fetch_match_update(match_url, match_name):
    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        m_id = match_url.split("/")[-2] if "/" in match_url else stable_event_suffix(match_name)

        # 1. GET STATUS TEXT FIRST (To catch Match End reliably)
        status_text = ""
        status_div = soup.find("div", class_=lambda x: x and any(c in x for c in ["text-cb-danger", "text-cb-info", "text-cb-success", "cb-text-complete", "cb-text-abandon"]))
        if status_div:
            status_text = status_div.get_text(strip=True)

        if not status_text:
            alt_status = soup.find(lambda tag: tag.name == "div" and tag.get("class") and any(phrase in tag.get_text(strip=True).lower() for phrase in ["won by", "abandoned", "target ", "innings break", "stumps", "no result"]))
            if alt_status and len(alt_status.get_text(strip=True)) < 100:
                status_text = alt_status.get_text(strip=True)

        status_lower = status_text.lower()
        is_match_over = is_result_text(status_lower)

        # 4. LOAD DATABASE STATE
        is_new_match = False
        try:
            row = cursor.execute(
                "SELECT last_over, last_wickets, toss_done, last_wicket_over, innings, last_double_strike_wk FROM state WHERE m_id=?",
                (m_id,),
            ).fetchone()
            if row:
                last_ov, last_wk, toss_done, last_wk_ov, current_innings, last_double_strike_wk = row
            else:
                last_ov, last_wk, toss_done, last_wk_ov, current_innings, last_double_strike_wk = (0.0, 0, 0, -10.0, 1, 0)
                is_new_match = True
        except Exception:
            last_ov, last_wk, toss_done, last_wk_ov, current_innings, last_double_strike_wk = (0.0, 0, 0, -10.0, 1, 0)
            is_new_match = True

        # 2. EXTRACT SCORE & TEAM LOGIC
        score_div = soup.find("div", class_=lambda x: x and (("text-3xl" in x and "font-bold" in x) or "cb-font-20" in x))
        
        team_batting = ""
        team_bowling = "Unknown"
        runs, wickets = 0, 0
        overs_raw = ""
        cur_overs, cur_balls = 0.0, 0
        score_display = ""
        full_score_text = ""

        if score_div:
            full_score_text = score_div.get_text(separator=" ", strip=True)
            
            # --- FIX: ISOLATE THE ACTIVE INNINGS ---
            active_score_text = full_score_text.split('&')[-1].strip()
            
            # --- SMART BATTING TEAM DETECTOR ---
            abbrev_match = re.search(r'^([A-Za-z]+)', active_score_text)
            if abbrev_match:
                abbrev = abbrev_match.group(1).upper()
                teams_in_match = [t.strip() for t in re.split(r'\s+vs\s+|\s+v\s+', match_name, flags=re.IGNORECASE)]
                
                overrides = {
                    "RSA": "South Africa", "SA": "South Africa",
                    "IND": "India", "AUS": "Australia", 
                    "ENG": "England", "NZ": "New Zealand",
                    "PAK": "Pakistan", "SL": "Sri Lanka", "SRI": "Sri Lanka",
                    "WI": "West Indies", "BAN": "Bangladesh", "ZIM": "Zimbabwe",
                    "AFG": "Afghanistan", "IRE": "Ireland"
                }
                
                if abbrev in overrides:
                    mapped = overrides[abbrev]
                    for t in teams_in_match:
                        if mapped.lower() in t.lower():
                            team_batting = t
                            break
                
                if not team_batting:
                    for t in teams_in_match:
                        words = t.split()
                        if len(words) > 1:
                            initials = "".join([w[0].upper() for w in words])
                            if abbrev == initials or abbrev.endswith(initials):
                                team_batting = t
                                break
                        if t.upper().startswith(abbrev):
                            team_batting = t
                            break

            # Fallback if Cricbuzz formatting is weird
            if not team_batting and status_text:
                teams_in_match = [t.strip() for t in re.split(r'\s+vs\s+|\s+v\s+', match_name, flags=re.IGNORECASE)]
                for t in teams_in_match:
                    if f"{t.lower()} need" in status_lower or f"{t.lower()} require" in status_lower or f"{t.lower()} trail" in status_lower:
                        team_batting = t
                        break
            
            # --- BOWLING TEAM IDENTIFICATION ---
            teams_in_match = [t.strip() for t in re.split(r'\s+vs\s+|\s+v\s+', match_name, flags=re.IGNORECASE)]
            if team_batting:
                for t in teams_in_match:
                    if t.lower() != team_batting.lower():
                        team_bowling = t
                        break

            # Parse numbers
            p = score_div.find_all("div")
            if p:
                runs_text = p[0].get_text(strip=True).replace(",", "")
                runs = int("".join(filter(str.isdigit, runs_text)) or 0)

                if len(p) > 1:
                    w_text = p[1].get_text(strip=True).replace("-", "").replace("/", "")
                    wickets = int(w_text) if w_text.isdigit() else 0

                if len(p) > 2:
                    overs_raw = p[2].get_text(strip=True).replace("(", "").replace(")", "")

                cur_overs = float(overs_raw) if overs_raw.replace(".", "", 1).isdigit() else 0.0
                cur_balls = overs_to_balls(overs_raw)
                score_display = f"{team_batting} {runs}/{wickets}" if team_batting else f"{runs}/{wickets}"

        # 3. GET COMMENTARY
        commentary_text = ""
        cm = soup.find("div", class_=lambda x: x and "leading-6" in x)
        if cm:
            eb = cm.find_all("div", recursive=False)
            if eb:
                t = eb[0] if "." in overs_raw else eb[-1]
                fl = t.find("div", class_=lambda x: x and "flex" in x and "gap-4" in x)
                if fl:
                    event_divs = fl.find_all("div", recursive=False)
                    if len(event_divs) >= 2:
                        commentary_text = event_divs[1].get_text(strip=True)

        event_text = status_text if status_text else commentary_text
        event_lower = event_text.lower()

        # Detect Innings switch natively
        if cur_overs < last_ov - 5:
            last_ov = 0.0
            last_wk = 0
            last_wk_ov = -10.0
            last_double_strike_wk = 0  # Reset for new innings
            current_innings = 2

        is_innings_break = (wickets == 10 and not is_match_over) or any(
            phrase in status_lower for phrase in ["innings break", "target", "stumps", "lunch", "tea"]
        )

        # Build Match Facts Dict for the AI
        match_facts = {
            "match_name": match_name,
            "event_type": "LIVE UPDATE",
            "team_batting": team_batting,
            "team_bowling": team_bowling,
            "innings": current_innings,
            "score_display": score_display,
            "status_text": status_text,
            "raw_data": full_score_text + " " + commentary_text
        }

        # FIX: The Database Loop Bug
        # We process DB insert for new match, but DO NOT silently return if the match is already over 
        # or at a break. This allows the bot to send the Winning/Innings post immediately.
        if is_new_match:
            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO state (m_id, last_over, last_wickets, toss_done, last_wicket_over, innings, last_double_strike_wk) VALUES (?,?,?,?,?,?,?)",
                    (m_id, cur_overs, wickets, toss_done, cur_overs, current_innings, last_double_strike_wk),
                )
                conn.commit()
            except sqlite3.Error:
                pass
            
            # Return early ONLY if it's mid-game. 
            if not is_match_over and not is_innings_break and wickets < 3:
                return

        msg = None

        # ==========================================
        # 🚨 THE STRICT EVENT HIERARCHY 🚨
        # ==========================================

        # 1. MATCH END LOGIC (Blocks over updates)
        if is_match_over:
            eid = f"{m_id}_MATCH_END"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                match_facts["event_type"] = "MATCH_END"
                msg = f"🏆 *MATCH COMPLETED: FINAL RESULT* 🏆\n—————————————————\n🎯 *{status_text}*\n\n🔹 {match_name}\n🔹 Final Score: *{score_display}* ({overs_raw})\n\n🖼 [Tap for Winning Moments]({get_img_link(match_name)})\n—————————————————\n✅ *Coverage concluded.*"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))
                
                # Un-comment the line below if you want the bot to auto-mute finished matches
                # cursor.execute("INSERT OR REPLACE INTO tracking_config VALUES (?, ?, 0)", (m_id, match_name))
                conn.commit()
                send_telegram(msg, pro_edit=True, match_facts=match_facts)
            
            # Must update state even on Match End
            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO state (m_id, last_over, last_wickets, toss_done, last_wicket_over, innings, last_double_strike_wk) VALUES (?,?,?,?,?,?,?)",
                    (m_id, cur_overs, wickets, toss_done, last_wk_ov, current_innings, last_double_strike_wk),
                )
                conn.commit()
            except sqlite3.Error: pass
            return # EXIT IMMEDIATELY!

        # 2. INNINGS BREAK
        elif is_innings_break:
            eid = f"{m_id}_INNINGS_BREAK_{runs}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                match_facts["event_type"] = "INNINGS_BREAK"
                msg = f"🛑 *INNINGS COMPLETED* 🛑\n—————————————————\n🏏 *{match_name}* finishes their innings.\n\n📊 *FINAL SCORE:* *{score_display}*\n🎯 *UPDATE:* _{status_text}_\n\n🖼 [Tap for Match Gallery]({get_img_link(match_name)})\n—————————————————\n🕒 _Second innings starts shortly._"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # 3. WEATHER ALERTS
        elif any(x in status_lower for x in ["rain", "drizzle", "interrupted", "delayed", "covers"]):
            eid = f"{m_id}_RAIN_{stable_event_suffix(status_text)}"
            if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                match_facts["event_type"] = "WEATHER_DELAY"
                msg = f"🌦 *WEATHER ALERT: {match_name}* 🌦\n—————————————————\n⚠️ {status_text}\n\n🕒 Match currently interrupted. Stay tuned for restart updates!"
                cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # 4. WICKET LOGIC
        elif wickets > last_wk:
            new_wk_ov = cur_overs
            if wickets == 3 and cur_overs <= 6.0 and last_wk < 3:
                eid = f"{m_id}_COLLAPSE_3WK"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    match_facts["event_type"] = "BATTING_COLLAPSE"
                    msg = f"🚨 *EARLY COLLAPSE* 🚨\n—————————————————\n💥 Huge trouble early on!\n\n🏏 *MATCH:* {match_name}\n📊 *SCORE:* *{score_display}* ({overs_raw})\n💬 *LATEST WICKET:* _{event_text}_\n\n🖼 [Tap for Match Action]({get_img_link(match_name)})\n—————————————————\n📉 *The batting side is under massive pressure!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))
            
            # --- FIX: DOUBLE STRIKE RESET LOGIC ---
            elif last_wk_ov > 0 and abs(cur_balls - overs_to_balls(str(last_wk_ov))) <= 6 and wickets >= last_double_strike_wk + 2:
                eid = f"{m_id}_DOUBLE_STRIKE_{wickets}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    match_facts["event_type"] = "DOUBLE_WICKET"
                    msg = f"🔥 *DOUBLE STRIKE* 🔥\n—————————————————\n🎯 Two quick wickets have changed the momentum!\n\n🏏 *MATCH:* {match_name}\n📊 *NEW SCORE:* *{score_display}* ({overs_raw})\n💬 *LATEST:* _{event_text}_\n\n🖼 [Tap for Celebration Photos]({get_img_link(match_name)})\n—————————————————\n⚠️ *Huge turning point in the game!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))
                    # Record that we sent an alert at this specific wicket count
                    last_double_strike_wk = wickets 
            
            last_wk_ov = new_wk_ov

        # 5. OVER MILESTONES (FORMAT AWARE)
        elif not msg:
            is_t20 = "T20" in match_name.upper()
            is_odi = "ODI" in match_name.upper()
            
            if is_t20:
                milestones = [6, 10, 15, 20]
            elif is_odi:
                milestones = [10, 20, 30, 40, 50]
            else:
                milestones = [10, 20, 30, 40, 50, 60, 70, 80, 90]

            passed_m = None
            for m in milestones:
                # FIX: `last_ov` is now always up-to-date at the bottom of the loop
                if last_ov < m and cur_overs >= m:
                    passed_m = m
                    break

            if passed_m:
                eid = f"{m_id}_OV_{passed_m}_{runs}_{current_innings}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    crr = f"{(runs / cur_overs):.2f}" if cur_overs else "N/A"
                    phase_header = f"{passed_m}-OVER"
                    if is_t20 and passed_m == 6:
                        phase_header = "POWERPLAY END"
                    elif is_t20 and passed_m in [15, 20]:
                        phase_header = "DEATH OVERS"

                    match_facts["event_type"] = f"{phase_header} SUMMARY"
                    msg = f"🏏 *{phase_header} UPDATE* 🏏\n—————————————————\n🏆 *{match_name}*\n\n📊 *SCORE:* *{score_display}*\n🕒 *OVERS:* {cur_overs}\n📈 *RUN RATE:* {crr}\n\n⚡ *LATEST:* _{event_text}_\n\n🖼 [Tap for Match Photos]({get_img_link(match_name)})\n—————————————————\n🔔 *Stay tuned for more live action!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # 6. PLAYER MILESTONES (50 / 100)
        if not msg:
            event_type = None
            speed_alert = ""

            balls_faced = 999
            ball_match = re.search(r"(\d+)\s*(balls|b)", event_lower)
            if ball_match:
                balls_faced = int(ball_match.group(1))

            if any(x in event_lower for x in ["fifty", "half-century", "half century", "50 runs", "reaches 50"]):
                event_type = "50"
                if balls_faced <= 25:
                    speed_alert = "⚡ EXPLOSIVE INNINGS ⚡\n"
            elif any(x in event_lower for x in ["century", "hundred", "100 runs", "reaches 100"]):
                event_type = "100"
                if balls_faced <= 50:
                    speed_alert = "⚡ SENSATIONAL CENTURY ⚡\n"

            if event_type:
                eid = f"{m_id}_MILESTONE_{stable_event_suffix(event_text)}"
                if not cursor.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
                    header = f"🔥 *{event_type} REACHED!* 🔥"
                    if speed_alert:
                        header = f"{speed_alert}{header}"
                    
                    match_facts["event_type"] = f"PLAYER {event_type} MILESTONE"
                    msg = f"{header}\n—————————————————\n⭐ *Player Milestone*\n\n🏏 *MATCH:* {match_name}\n📊 *CURRENT SCORE:* *{score_display}* ({overs_raw})\n💬 *COMMENTARY:* _{event_text}_\n\n🖼 [Tap for Player Photos]({get_img_link(match_name + ' ' + event_text)})\n—————————————————\n👏 *What a knock! Share the news!*"
                    cursor.execute("INSERT INTO events VALUES (?)", (eid,))

        # FIRE TELEGRAM MESSAGE
        if msg:
            send_telegram(msg, pro_edit=True, match_facts=match_facts)

        # UPDATE DB STATE - FIX: This must always fire to ensure tracking doesn't stall
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO state (m_id, last_over, last_wickets, toss_done, last_wicket_over, innings, last_double_strike_wk) VALUES (?,?,?,?,?,?,?)",
                (m_id, cur_overs, wickets, toss_done, last_wk_ov, current_innings, last_double_strike_wk),
            )
        except sqlite3.Error:
            pass

        conn.commit()
    except Exception as e:
        logger.error(f"fetch_match_update failed for {match_url}:\n{traceback.format_exc()}")

def run_bot():
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Missing BOT_TOKEN and/or CHAT_ID. Bot cannot start.")
        return

    logger.info("🚀 WhatsApp Content Assistant & Narrative AI Engine Starting...")
    send_telegram(
        "✅ *Live-Only Tracker Active!* 🏏\n- Zero spam guaranteed.\n- Use /stop to kill unwanted matches."
    )

    while True:
        try:
            handle_commands()
            handle_daily_briefing()

            matches = scrape_match_links()
            for name, link in matches:
                m_id = link.split("/")[-2]

                row = cursor.execute(
                    "SELECT is_active FROM tracking_config WHERE m_id=?", (m_id,)
                ).fetchone()
                
                # Apply default mute logic for Women's matches
                default_active = 0 if is_womens_match(name) else 1
                is_tracking = row[0] if row else default_active

                if is_tracking == 0:
                    continue

                fetch_toss_update(link, name)
                fetch_match_update(link, name)

        except Exception as e:
            logger.error(f"Main Loop Error:\n{traceback.format_exc()}")

        time.sleep(15)

if __name__ == "__main__":
    run_bot()
