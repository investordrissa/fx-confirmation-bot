import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS


def send_alert(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {"chat_id": chat_id, "text": text}
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(result)
