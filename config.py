import os

PAIRS = [
    "EUR/USD","GBP/USD","USD/JPY","USD/CHF","USD/CAD","AUD/USD","NZD/USD",
    "EUR/GBP","EUR/JPY","EUR/CHF","EUR/CAD","EUR/AUD","EUR/NZD",
    "GBP/JPY","GBP/CHF","GBP/CAD","GBP/AUD","GBP/NZD",
    "AUD/JPY","AUD/CHF","AUD/CAD","AUD/NZD","NZD/JPY","NZD/CHF","NZD/CAD",
    "CAD/JPY","CAD/CHF","CHF/JPY",
    "XAU/USD","BTC/USD","ETH/USD"
]

TIMEFRAMES = {"weekly": "1week", "daily": "1day", "4h": "4h"}

MAX_ENTRY_DISTANCE_PIPS = 30
SL_BUFFER_PIPS = 5
BREAKEVEN_R = 1.0
TP_R_MIN = 3.0
TP_R_MAX = 4.0

SCAN_SECONDS = 300
OUTPUT_SIZE = 500

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1633187346")
TELEGRAM_CHAT_IDS = [TELEGRAM_CHAT_ID, "6513210876"]

BE_PAIRS = {
    "EUR/USD": True, "GBP/USD": True, "AUD/USD": True, "USD/CAD": True,
    "NZD/USD": True, "EUR/GBP": True, "EUR/AUD": True, "EUR/NZD": True,
    "GBP/NZD": True, "AUD/NZD": True, "GBP/JPY": True, "AUD/JPY": True,
    "USD/JPY": False, "USD/CHF": False, "EUR/JPY": False, "EUR/CHF": False,
    "EUR/CAD": False, "GBP/CHF": False, "GBP/AUD": False, "GBP/CAD": False,
    "AUD/CHF": False, "AUD/CAD": False, "NZD/JPY": False, "NZD/CHF": False,
    "NZD/CAD": False, "CAD/JPY": False, "CAD/CHF": False, "CHF/JPY": False,
    "BTC/USD": True, "ETH/USD": True,
}
