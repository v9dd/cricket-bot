import requests
from bs4 import BeautifulSoup
import time
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

sent = set()

def send_message(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    requests.post(url, data=data)

def get_scores():
    url = "https://www.cricbuzz.com/live-cricket-scores"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")
    matches = soup.find_all("div", class_="cb-mtch-lst")
    return [m.get_text(" ", strip=True) for m in matches]

while True:
    try:
        scores = get_scores()
        for score in scores:
            if score not in sent:
                send_message(f"🏏 LIVE UPDATE\n\n{score}")
                sent.add(score)
                print("Sent:", score)
    except Exception as e:
        print(e)

    time.sleep(15)
