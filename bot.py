import requests
import os
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# store last event per match
last_events = {}
def fetch_toss_update(match_url, match_name):

    try:

        # Convert to scorecard URL
        scorecard_url = match_url.replace(
            "live-cricket-scores",
            "live-cricket-scorecard"
        )

        response = requests.get(scorecard_url, headers=HEADERS, timeout=15)

        if response.status_code != 200:
            print(f"Failed to fetch scorecard for {match_name}")
            return

        soup = BeautifulSoup(response.text, "html.parser")

        # Find Toss label
        toss_label = soup.find(
            "div",
            class_="font-bold",
            string="Toss"
        )

        if not toss_label:
            print(f"Toss not found yet for {match_name}")
            return

        # Get next div containing toss text
        toss_text_div = toss_label.find_next("div")

        if not toss_text_div:
            return

        toss_text = toss_text_div.get_text(strip=True)

        # prevent duplicates
        if match_url in match_state and match_state[match_url].get("toss_sent"):
            return

        if match_url not in match_state:
            match_state[match_url] = {}

        match_state[match_url]["toss_sent"] = True

        timestamp = datetime.now().strftime("%H:%M")

        message = (
            f"🪙 TOSS UPDATE 🪙\n\n"
            f"{match_name}\n\n"
            f"{toss_text}\n\n"
            f"🕒 {timestamp}\n"
            f"🔗 {match_url}"
        )

        print(message)

        send_message(message)

    except Exception as e:
        print(f"Toss fetch error for {match_name}: {e}")

def send_message(text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }

    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print("Telegram error:", e)


# get latest score (runs-wickets overs)
def get_score_and_over(soup):

    score_div = soup.find(
        "div",
        class_=lambda x: x and "text-3xl" in x and "font-bold" in x
    )

    if not score_div:
        return None, None

    runs = score_div.find_all("div")[0].get_text(strip=True)

    wickets = score_div.find_all("div")[1].get_text(strip=True).replace("-", "")

    overs = score_div.find_all("div")[2].get_text(strip=True)

    overs = overs.replace("(", "").replace(")", "")

    score = f"{runs}-{wickets}"

    return score, overs


# get latest ball event
def get_latest_event(soup):

    main = soup.find("div", class_=lambda x: x and "mb-2" in x)

    if not main:
        return None

    first_row = main.find("div", recursive=False)

    if not first_row:
        return None

    event = first_row.get_text(strip=True)

    return event


# fetch latest data from match link
def fetch_match_update(match_url, match_name):

    try:
        response = requests.get(match_url, headers=HEADERS, timeout=15)

        if response.status_code != 200:
            print(f"Failed to fetch {match_name}")
            return

        soup = BeautifulSoup(response.text, "html.parser")


        # =========================
        # GET SCORE AND CURRENT OVER
        # =========================

        score_div = soup.find(
            "div",
            class_=lambda x: x and "text-3xl" in x and "font-bold" in x
        )

        if not score_div:
            print(f"Score not found for {match_name}")
            return

        score_parts = score_div.find_all("div")

        runs = score_parts[0].get_text(strip=True)

        wickets = score_parts[1].get_text(strip=True).replace("-", "")

        overs = score_parts[2].get_text(strip=True)
        overs = overs.replace("(", "").replace(")", "")

        score = f"{runs}-{wickets}"


        # =========================
        # GET LATEST EVENT (YOUR EXACT STRUCTURE)
        # =========================

        commentary_main = soup.find(
            "div",
            class_=lambda x: x and "leading-6" in x
        )

        if not commentary_main:
            print(f"No commentary container found for {match_name}")
            return

        first_wrapper = commentary_main.find("div", recursive=False)

        if not first_wrapper:
            print(f"No first wrapper found for {match_name}")
            return

        flex_row = first_wrapper.find(
            "div",
            class_=lambda x: x and "flex" in x and "gap-4" in x
        )

        if not flex_row:
            print(f"No flex row found for {match_name}")
            return

        event_divs = flex_row.find_all("div", recursive=False)

        if len(event_divs) < 2:
            print(f"No event div found for {match_name}")
            return

        event_text = event_divs[1].get_text(strip=True)


        # =========================
        # PREVENT DUPLICATES
        # =========================

        unique_id = f"{match_url}_{score}_{event_text}"

        if match_url in last_events and last_events[match_url] == unique_id:
            return

        last_events[match_url] = unique_id


        # =========================
        # TIMESTAMP
        # =========================

        timestamp = datetime.now().strftime("%H:%M:%S")


        # =========================
        # MESSAGE FORMAT
        # =========================

        message = (
            f"🏏 {match_name}\n\n"
            f"📊 Score: {score} ({overs})\n"
            f"🔥 Event: {event_text}\n\n"
            f"🕒 {timestamp}\n"
            f"🔗 {match_url}"
        )


        print("\nSending update:")
        print(message)
        print("--------------------------------------------------")


        send_message(message)


    except Exception as e:
        print(f"Error fetching match update for {match_name}: {e}")
# scrape match links from Cricbuzz live scores page
def scrape_match_links():

    url = "https://www.cricbuzz.com/cricket-match/live-scores"

    response = requests.get(url, headers=HEADERS)

    soup = BeautifulSoup(response.text, "html.parser")

    main_container = soup.find("div", class_="flex flex-col gap-2")

    matches = []

    blocks = main_container.find_all("div", recursive=False)

    for block in blocks:

        cards = block.select("a.w-full.bg-cbWhite")

        for card in cards:

            name = card.get("title", "").strip()

            if not name:
                continue

            link = "https://www.cricbuzz.com" + card["href"]

            matches.append((name, link))

    return matches


def main():

    print("Live match bot started...")

    while True:

        try:

            matches = scrape_match_links()

            for match_name, match_link in matches:
                fetch_toss_update(match_link, match_name)
                fetch_match_update(match_link, match_name)

        except Exception as e:
            print("Error:", e)

        time.sleep(15)   # interval in seconds


if __name__ == "__main__":
    main()
