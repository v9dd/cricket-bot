import os
import time
import sqlite3
import requests
from bs4 import BeautifulSoup
from google import genai

# 1. NO CRICKET API KEYS NEEDED
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY or not BOT_TOKEN:
    print("🚨 SYSTEM HALTED: Missing Telegram or Gemini Keys!")
    time.sleep(60)
    exit()

client = genai.Client() 

# 2. Database Setup
conn = sqlite3.connect("cricket.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS state (m_id TEXT PRIMARY KEY, last_over REAL, toss_done INTEGER DEFAULT 0)")
conn.commit()

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
            model='gemini-2.0-flash',
            contents=f"Using the exact WhatsApp channel format we locked in previously, write professional cricket news for this update: {prompt}"
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

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
                send_telegram("🏏 Scraping live data directly from Cricbuzz...")
                fetch_live_summary()
    except Exception:
        pass

# =====================
# THE DIRECT WEB SCRAPER
# =====================
def fetch_live_summary():
    url = "https://www.cricbuzz.com/cricket-match/live-scores"
    # We use a User-Agent so Cricbuzz thinks the bot is a normal Chrome browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.content, 'html.parser')
        
        matches_found = []
        
        # Cricbuzz wraps their individual match boxes in this specific class
        match_blocks = soup.find_all('div', class_='cb-mtch-lst')
        
        for block in match_blocks[:5]:
            # Extract all the text from the block and remove extra whitespace
            raw_text = block.text.strip()
            clean_text = " ".join(raw_text.split())
            if clean_text:
                matches_found.append(clean_text)
        
        if not matches_found:
            send_telegram("There are no live matches on Cricbuzz right now.")
            return
            
        # We hand the raw, scraped text directly to Gemini. It is smart enough to extract the scores.
        prompt = f"I scraped this raw text directly from the Cricbuzz website: {matches_found}. Please extract the teams, scores, and match status, and provide a quick, punchy update."
        msg = get_ai_news(prompt)
        
        if msg: 
            send_telegram(msg)
            
    except Exception as e:
        print(f"Scraper Error: {e}")
        send_telegram("⚠️ System error while scraping the website.")

if __name__ == "__main__":
    print("🚀 Cricket Newsroom Worker Starting with DIRECT SCRAPER...")
    send_telegram("✅ Bot Online! Now scraping directly from the source. Type /score to test.")
    while True:
        handle_commands() 
        time.sleep(10)
