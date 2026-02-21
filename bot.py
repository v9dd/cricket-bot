import requests
import time
import os
import re
from bs4 import BeautifulSoup

print("Bot is starting (Global Mode with News)...")

# Load Telegram credentials from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Track already sent updates across all matches
sent_updates = set()

def send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Error: BOT_TOKEN or CHAT_ID not set")
        return

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": text}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Telegram send error:", e)

def get_latest_news():
    """Fetches the latest news headline from Cricbuzz."""
    try:
        url = "https://www.cricbuzz.com/cricket-news"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        # Cricbuzz news structure usually has headers in h2 or h3 within cb-col-67
        news_item = soup.find('a', class_='cb-nws-hdln-ancr')
        if news_item:
            headline = news_item.get_text(strip=True)
            link = "https://www.cricbuzz.com" + news_item['href']
            # Also try to get intro text
            intro = news_item.find_next('div', class_='cb-nws-intr')
            intro_text = intro.get_text(strip=True) if intro else ""
            return f"📰 Latest News: {headline}\n\n{intro_text}\n\nRead more: {link}"
        return None
    except Exception as e:
        print("Error fetching news:", e)
        return None

def get_live_matches():
    """Fetches currently live matches from Cricbuzz."""
    try:
        url = "https://www.cricbuzz.com/cricket-match/live-scores"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', href=re.compile(r'/live-cricket-scores/\d+/'))
        
        match_ids = []
        for link in links:
            match = re.search(r'/live-cricket-scores/(\d+)/', link['href'])
            if match:
                match_ids.append(match.group(1))
        
        return list(set(match_ids))
    except Exception as e:
        print("Error fetching live matches:", e)
        return []

def get_match_commentary(match_id):
    """Fetches commentary for a specific match ID."""
    try:
        url = f"https://www.cricbuzz.com/live-cricket-scores/{match_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return [], "Unknown Match"

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get Match Name
        title_tag = soup.find('h1', class_='cb-nav-hdr')
        match_name = title_tag.get_text(strip=True).replace('Commentary', '').strip() if title_tag else f"Match {match_id}"
        
        results = []
        items = soup.find_all(['div', 'p', 'span'], class_=re.compile('cb-comm-item|cb-com-ln|cb-col-100|cb-ovr-num'))
        
        for item in items:
            text = item.get_text(separator=' ', strip=True)
            if not text or len(text) < 20:
                continue
            
            # Create a unique ID combining match and text
            item_id = f"{match_id}_{hash(text)}"
            results.append({"id": item_id, "text": text})

        return results, match_name
    except Exception as e:
        print(f"Error scraping match {match_id}:", e)
        return [], "Error"

def main():
    print("Fetching initial data...")
    
    # Send latest news on start
    news = get_latest_news()
    if news:
        send_message(news)
        print("Sent latest news on startup.")
    
    # Initialize with current match data to avoid spamming history
    live_matches = get_live_matches()
    for m_id in live_matches:
        updates, _ = get_match_commentary(m_id)
        for u in updates:
            sent_updates.add(u["id"])
    print(f"Initialized with {len(live_matches)} matches and {len(sent_updates)} history items.")

    while True:
        try:
            live_matches = get_live_matches()
            if not live_matches:
                print("No live matches found currently.")
            
            for m_id in live_matches:
                updates, match_name = get_match_commentary(m_id)
                
                new_updates = 0
                for update in reversed(updates):
                    if update["id"] not in sent_updates:
                        message = f"🏏 {match_name}\n\n{update['text']}"
                        send_message(message)
                        sent_updates.add(update["id"])
                        new_updates += 1
                
                if new_updates > 0:
                    print(f"Sent {new_updates} new updates for {match_name}.")

            # Memory management
            if len(sent_updates) > 3000:
                sent_updates.clear()

        except Exception as e:
            print("Main loop error:", e)

        time.sleep(60)

if __name__ == "__main__":
    main()
