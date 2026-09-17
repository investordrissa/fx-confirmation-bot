import json
import os

from data_feed import get_candles
from config import TELEGRAM_BOT_TOKEN
import requests

ALERTS_FILE = "price_alerts.json"


def load_alerts():
    if not os.path.exists(ALERTS_FILE):
        return []
    with open(ALERTS_FILE) as f:
        return json.load(f)


def save_alerts(alerts):
    tmp = ALERTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(alerts, f, indent=2)
    os.replace(tmp, ALERTS_FILE)


def send_to(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)


def get_current_price(pair):
    df = get_candles(pair, "1min", 1)
    if hasattr(df, "empty"):
        if df.empty:
            return None
        return float(df.iloc[-1]["close"])
    if not df:
        return None
    return float(df[-1].close)


def main():
    alerts = load_alerts()
    if not alerts:
        print("No pending price alerts.")
        return

    remaining = []
    for alert in alerts:
        pair = alert["pair"]
        target = alert["price"]
        direction = alert["direction"]
        chat_id = alert["chat_id"]

        price = get_current_price(pair)
        if price is None:
            print(f"Could not fetch price for {pair}, keeping alert.")
            remaining.append(alert)
            continue

        triggered = (
            (direction == "above" and price >= target)
            or (direction == "below" and price <= target)
        )

        if triggered:
            send_to(
                chat_id,
                f"🔔 Price Alert: {pair} is now {direction} {target} (current: {price})",
            )
            print(f"Triggered: {pair} {direction} {target} (price={price})")
        else:
            remaining.append(alert)

    save_alerts(remaining)


if __name__ == "__main__":
    main()
