import requests
import os
import time
from bs4 import BeautifulSoup
from datetime import datetime

# 1. 100% API LIMIT FREE - NO GEMINI NEEDED!
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not BOT_TOKEN:
    print("🚨 SYSTEM HALTED: Missing Telegram Token!")
    time.sleep(60)
    exit()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# State management directly from your v1 code
match_state = {}
last_events = {}
last_update_id = None

def send_telegram(text):
    if not text: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

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
            msg_data = update.get("message") or update.get("channel_post")
            if not msg_data: continue
            text = msg_data.get("text", "")
            
            if "/score" in text:
                send_telegram("🏏 *Fetching live scores...*")
                
                matches = scrape_match_links()
                if not matches:
                    send_telegram("⚠️ There are no live matches on Cricbuzz right now.")
                    continue
                
                summary_data = []
                for name, link in matches[:5]:
                    score = scrape_instant_score(link)
                    summary_data.append(f"🔹 *{name}*\n📊 {score}")
                
                # NATIVE FORMATTING (Bypasses AI completely)
                final_msg = "🏆 *LIVE CRICKET SCORES* 🏆\n\n" + "\n\n".join(summary_data)
                send_telegram(final_msg)
                
    except Exception as e:
        print(f"Command Error: {e}")

# =====================
# YOUR V1 SCRAPING ENGINE
# =====================
def scrape_match_links():
    url = "https://www.cricbuzz.com/cricket-match/live-scores"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        main_container = soup.find("div", class_="flex flex-col gap-2")
        matches = []
        if not main_container: return matches
        
        blocks = main_container.find_all("div", recursive=False)
        for block in blocks:
            cards = block.select("a.w-full.bg-cbWhite")
            for card in cards:
                name = card.get("title", "").strip()
                if not name: continue
                link = "https://www.cricbuzz.com" + card["href"]
                matches.append((name, link))
        return matches
    except Exception as e:
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
    if match_state[match_url]["toss_sent"]:
        return

    scorecard_url = match_url.replace("live-cricket-scores", "live-cricket-scorecard").replace("www.cricbuzz.com", "m.cricbuzz.com")

    try:
        response = requests.get(scorecard_url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return

        soup = BeautifulSoup(response.text, "html.parser")
        toss_label = soup.find(lambda tag: tag.name == "div" and "font-bold" in tag.get("class", []) and "Toss" in tag.get_text())
        if not toss_label: return

        toss_text = toss_label.find_next("div").get_text(strip=True)
        match_state[match_url]["toss_sent"] = True

        # NATIVE FORMATTING FROM YOUR V1
        message = (
            f"🪙 *TOSS UPDATE* 🪙\n\n"
            f"*{match_name}*\n\n"
            f"{toss_text}\n\n"
            f"🔗 [Match Link]({match_url})"
        )
        send_telegram(message)

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

        commentary_main = soup.find("div", class_=lambda x: x and "leading-6" in x)
        if not commentary_main: return
        
        event_blocks = commentary_main.find_all("div", recursive=False)
        if not event_blocks: return
        
        if "." in overs:
            target_block = event_blocks[0]
        else:
            target_block = event_blocks[1] if len(event_blocks) > 1 else event_blocks[0]
        
        flex_row = target_block.find("div", class_=lambda x: x and "flex" in x and "gap-4" in x)
        if not flex_row: return
        
        event_divs = flex_row.find_all("div", recursive=False)
        if len(event_divs) < 2: return
        
        event_text = event_divs[1].get_text(strip=True)

        unique_id = f"{match_url}_{score}_{event_text}"
        if match_url in last_events and last_events[match_url] == unique_id:
            return

        last_events[match_url] = unique_id
        timestamp = datetime.now().strftime("%H:%M:%S")

        # NATIVE FORMATTING FROM YOUR V1
        message = (
            f"🏏 *{match_name}*\n\n"
            f"📊 *Score:* {score} ({overs})\n"
            f"🔥 *Event:* {event_text}\n\n"
            f"🕒 {timestamp}\n"
            f"🔗 [Live Score]({match_url})"
        )
        send_telegram(message)

    except Exception:
        pass

if __name__ == "__main__":
    print("🚀 Cricket Newsroom Worker Starting...")
    send_telegram("✅ *Bot Online!* Running cleanly with NO API Limits. Type /score to check.")
    
    while True:
        try:
            handle_commands()
            matches = scrape_match_links()
            
            for match_name, match_link in matches:
                fetch_toss_update(match_link, match_name)
                fetch_match_update(match_link, match_name)
                
        except Exception as e:
            print("Loop Error:", e)
            
        # Safe 15-second loop because there are ZERO API limits now
        time.sleep(15)
