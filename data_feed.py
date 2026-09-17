import time
import requests
import pandas as pd
from config import TWELVE_DATA_API_KEY

BASE_URL = "https://api.twelvedata.com/time_series"

# Twelve Data free plan: keep requests below 8/min
REQUEST_DELAY = 8.5
_last_request = 0.0

# Cache data so the 5-minute scanner does NOT request
# the same candles over and over.
_cache = {}


def cache_ttl(interval):
    if interval == "1week":
        return 7 * 24 * 60 * 60
    if interval == "1day":
        return 24 * 60 * 60
    if interval == "4h":
        return 4 * 60 * 60
    if interval == "1min":
        return 30
    return 60 * 60


def get_candles(symbol: str, interval: str, outputsize: int):
    global _last_request

    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY")

    key = (symbol, interval)
    now = time.time()

    # Return cached data when it is still fresh
    if key in _cache:
        saved_time, df = _cache[key]
        if now - saved_time < cache_ttl(interval):
            return df.copy()

    # Respect API request spacing
    elapsed = now - _last_request
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "order": "ASC",
    }

    response = requests.get(
        BASE_URL,
        params=params,
        timeout=30
    )

    _last_request = time.time()

    if response.status_code == 429:
        raise RuntimeError(
            "Twelve Data rate limit reached. "
            "Wait and try again."
        )

    response.raise_for_status()

    data = response.json()

    if "values" not in data:
        raise RuntimeError(
            f"Twelve Data error for {symbol} {interval}: {data}"
        )

    df = pd.DataFrame(data["values"])

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["datetime"] = pd.to_datetime(df["datetime"])

    df = df.sort_values("datetime").reset_index(drop=True)

    _cache[key] = (time.time(), df)

    return df.copy()
