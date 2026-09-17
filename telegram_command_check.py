import json
import os
import re
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS

OFFSET_FILE = "telegram_offset.json"
ALERTS_FILE = "price_alerts.json"

ALERT_RE = re.compile(
    r"^/alert\s+([A-Za-z]{3}/[A-Za-z]{3})\s+([\d.]+)\s+(above|below)$",
    re.IGNORECASE,
)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main():
    offset_data = load_json(OFFSET_FILE, {"offset": 0})
    alerts = load_json(ALERTS_FILE, [])

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": offset_data["offset"], "timeout": 5}
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        print("getUpdates failed:", data)
        return

    updates = data.get("result", [])
    added = 0

    for update in updates:
        offset_data["offset"] = update["update_id"] + 1
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()

        if chat_id not in [str(c) for c in TELEGRAM_CHAT_IDS]:
            continue

        match = ALERT_RE.match(text)
        if match:
            pair, price, direction = match.groups()
            pair = pair.upper()
            alerts.append({
                "pair": pair,
                "price": float(price),
                "direction": direction.lower(),
                "chat_id": chat_id,
            })
            added += 1

    save_json(OFFSET_FILE, offset_data)
    save_json(ALERTS_FILE, alerts)
    print(f"Checked {len(updates)} updates, added {added} new price alerts.")


if __name__ == "__main__":
    main()
