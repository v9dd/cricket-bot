import requests
import time
import os

print("Bot is starting...")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

MATCH_ID = "133633"

sent = set()

def send_message(text):

    print("Sending message:", text)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": text
    }

    r = requests.post(url, data=data)

    print("Telegram response:", r.text)


def get_commentary():

    print("Fetching commentary...")

    url = f"https://www.cricbuzz.com/api/cricket-match/commentary/{MATCH_ID}"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.cricbuzz.com/"
    }

    r = requests.get(url, headers=headers)

    print("Cricbuzz response code:", r.status_code)

    if r.status_code != 200:
        return []

    data = r.json()

    if "commentaryList" not in data:
        print("No commentary found")
        return []

    return data["commentaryList"]


while True:

    print("Loop running...")

    try:

        balls = get_commentary()

        for ball in balls:

            if "commText" in ball and "timestamp" in ball:

                ball_id = str(ball["timestamp"])

                if ball_id not in sent:

                    text = ball.get("commText", "")

                    message = f"🏏 VIC vs WA\n\n{text}"

                    send_message(message)

                    sent.add(ball_id)

    except Exception as e:

        print("ERROR:", e)

    time.sleep(10)
