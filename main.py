
Multi-timeframe forex confirmation bot.

Strategy (as defined by the user):
  RULE 1 - Price returns to a valid WEEKLY key area (OB / FVG / S&R / swing high-low), any age.
  RULE 2 - Weekly engulfing confirmation: full body close-through (Type A)
           OR liquidity sweep + 50%+ close-back (Type B).
  RULE 3 - Price retests the confirmation candle's body -> switch to DAILY.
  RULE 4 - Daily BSL/SSL sweep (current or previous week's daily candles) -> switch to H4.
  RULE 5 - H4 confirmation: liquidity taken OR fake move, then displacement,
           then HH/HL (long) or LH/LL (short) structure, then a decisive close.
  RULE 6 - If liquidity-to-close distance on H4 <= 30 pips -> enter immediately.
           If > 30 pips -> wait for a retracement into the entry zone.

Risk management:
  SL = swept liquidity level +/- 5 pip buffer
  Move SL to breakeven at 1:1
  Target RR = 1:3 to 1:4

This script is designed to be run periodically (e.g. hourly, via GitHub Actions).
It is STATELESS between runs except for state.json, which it reads and rewrites
each run so it remembers which stage each pair is at and doesn't send duplicate
alerts for the same setup.

Credentials are read from environment variables:
  TWELVE_DATA_API_KEY
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""

import os
import json
import time
import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

TWELVE_DATA_API_KEY = os.environ["TWELVE_DATA_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

# Broad pair list. Twelve Data free tier = 800 credits/day, 8/min.
# Each pair needs 3 calls (1W, 1D, 4H) per run -> keep the run frequency
# and pair count balanced against that budget (see README for the math).
PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/CAD", "EUR/AUD", "EUR/NZD",
    "GBP/JPY", "GBP/CHF", "GBP/CAD", "GBP/AUD", "GBP/NZD",
    "AUD/JPY", "AUD/CAD", "AUD/CHF", "AUD/NZD",
    "NZD/JPY", "NZD/CAD", "NZD/CHF",
    "CAD/JPY", "CAD/CHF", "CHF/JPY",
]

BSL_SSL_LOOKBACK_WEEKLY = 1       # compare vs previous weekly candle
DAILY_LOOKBACK_WEEKS = 2          # current week + previous week of daily candles
IMMEDIATE_ENTRY_PIP_THRESHOLD = 30

# ---------------------------------------------------------------------------
# DATA FETCHING
# ---------------------------------------------------------------------------

TD_BASE_URL = "https://api.twelvedata.com/time_series"


def fetch_candles(pair, interval, outputsize=60):
    """Fetch OHLC candles from Twelve Data. Returns oldest-first list of dicts."""
    params = {
        "symbol": pair,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "order": "ASC",
    }
    resp = requests.get(TD_BASE_URL, params=params, timeout=30)
    data = resp.json()
    if "values" not in data:
        print(f"  ! Failed to fetch {pair} {interval}: {data}")
        return None
    candles = []
    for row in data["values"]:
        candles.append({
            "datetime": row["datetime"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    return candles


def pip_size(pair):
    """JPY-quoted pairs use 0.01 as one pip; everything else uses 0.0001."""
    return 0.01 if pair.endswith("JPY") else 0.0001


# ---------------------------------------------------------------------------
# STATE PERSISTENCE
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_pair_state(state, pair):
    return state.setdefault(pair, {
        "stage": "watching_weekly",   # watching_weekly -> weekly_confirmed -> daily_confirmed -> h4_confirmed -> in_trade
        "bias": None,                 # "long" or "short"
        "weekly_confirm_candle": None,
        "daily_liquidity_level": None,
        "h4_liquidity_level": None,
        "entry": None,
        "sl": None,
        "tp": None,
        "breakeven_done": False,
    })


# ---------------------------------------------------------------------------
# CANDLE HELPERS
# ---------------------------------------------------------------------------

def is_bullish(c):
    return c["close"] > c["open"]


def body_high(c):
    return max(c["open"], c["close"])


def body_low(c):
    return min(c["open"], c["close"])


def body_midpoint(c):
    return (c["open"] + c["close"]) / 2


# ---------------------------------------------------------------------------
# RULE 1 + KEY-LEVEL DETECTION (weekly order blocks / swing levels)
# ---------------------------------------------------------------------------

def find_weekly_key_levels(weekly_candles, lookback=52):
    """
    Very simplified OB detector: the last opposite-colored candle before an
    impulsive move (a candle whose body is at least 1.5x the average body
    size of the preceding 5 candles) is flagged as an OB.
    Returns a list of {"index", "type": "bullish"/"bearish", "high", "low"}.
    """
    levels = []
    candles = weekly_candles[-lookback:] if len(weekly_candles) > lookback else weekly_candles
    for i in range(5, len(candles) - 1):
        window = candles[i - 5:i]
        avg_body = sum(abs(c["close"] - c["open"]) for c in window) / len(window)
        impulsive = candles[i + 1]
        impulsive_body = abs(impulsive["close"] - impulsive["open"])
        if impulsive_body >= 1.5 * avg_body and avg_body > 0:
            candidate = candles[i]
            if is_bullish(impulsive) and not is_bullish(candidate):
                levels.append({"index": i, "type": "bullish_ob", "high": candidate["high"], "low": candidate["low"]})
            elif not is_bullish(impulsive) and is_bullish(candidate):
                levels.append({"index": i, "type": "bearish_ob", "high": candidate["high"], "low": candidate["low"]})
    return levels


def price_in_zone(price, low, high):
    return low <= price <= high


# ---------------------------------------------------------------------------
# RULE 2 - WEEKLY ENGULFING CONFIRMATION
# ---------------------------------------------------------------------------

def check_weekly_engulfing(prev, curr):
    """
    Returns "long", "short", or None.
    Type A: curr body fully closes beyond prev body (open/close).
    Type B: curr wicks beyond prev high/low (sweep) but closes back,
            counts if curr close is beyond prev body's 50% midpoint.
    """
    prev_mid = body_midpoint(prev)

    # Bullish attempt
    if is_bullish(curr):
        full_close = curr["close"] > body_high(prev) and curr["open"] < body_low(prev)
        swept_low = curr["low"] < prev["low"]
        close_back_above_mid = curr["close"] >= prev_mid
        if full_close:
            return "long"
        if swept_low and close_back_above_mid:
            return "long"

    # Bearish attempt
    if not is_bullish(curr):
        full_close = curr["close"] < body_low(prev) and curr["open"] > body_high(prev)
        swept_high = curr["high"] > prev["high"]
        close_back_below_mid = curr["close"] <= prev_mid
        if full_close:
            return "short"
        if swept_high and close_back_below_mid:
            return "short"

    return None


# ---------------------------------------------------------------------------
# RULE 3 - RETEST CHECK
# ---------------------------------------------------------------------------

def price_retested_body(confirm_candle, latest_price):
    return price_in_zone(latest_price, body_low(confirm_candle), body_high(confirm_candle))


# ---------------------------------------------------------------------------
# RULE 4 - DAILY BSL/SSL SWEEP
# ---------------------------------------------------------------------------

def find_daily_liquidity_levels(daily_candles, weeks=2):
    """Return recent daily swing highs/lows from the last `weeks` weeks (~5 candles/week)."""
    recent = daily_candles[-(weeks * 5):]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    return {"highs": highs, "lows": lows}


def check_daily_sweep(latest_candle, levels, bias):
    if bias == "long":
        for low in levels["lows"]:
            if latest_candle["low"] < low:
                return low
    else:
        for high in levels["highs"]:
            if latest_candle["high"] > high:
                return high
    return None


# ---------------------------------------------------------------------------
# RULE 5 - H4 CONFIRMATION (liquidity/fake move + displacement + structure + close)
# ---------------------------------------------------------------------------

def check_h4_confirmation(h4_candles, daily_liquidity_level, bias, tolerance_pips, pip):
    """
    Simplified check across the most recent H4 candles:
    - price must have come within `tolerance_pips` of the daily liquidity level
      (or swept it directly)
    - the most recent candle must close decisively in the bias direction
    - a basic HH/HL or LH/LL structure check over the last 3 candles
    Returns the liquidity level used for H4 confirmation, or None.
    """
    if len(h4_candles) < 4:
        return None

    tolerance = tolerance_pips * pip
    recent = h4_candles[-4:]
    last = recent[-1]

    near_level = any(
        abs(c["high"] - daily_liquidity_level) <= tolerance or
        abs(c["low"] - daily_liquidity_level) <= tolerance or
        (bias == "long" and c["low"] < daily_liquidity_level) or
        (bias == "short" and c["high"] > daily_liquidity_level)
        for c in recent
    )
    if not near_level:
        return None

    if bias == "long":
        structure_ok = recent[-1]["low"] > recent[-3]["low"] and recent[-1]["high"] > recent[-3]["high"]
        decisive_close = is_bullish(last)
    else:
        structure_ok = recent[-1]["low"] < recent[-3]["low"] and recent[-1]["high"] < recent[-3]["high"]
        decisive_close = not is_bullish(last)

    if structure_ok and decisive_close:
        return daily_liquidity_level

    return None


# ---------------------------------------------------------------------------
# RULE 6 + RISK MANAGEMENT
# ---------------------------------------------------------------------------

def compute_trade_plan(confirm_candle, liquidity_level, bias, pip):
    close = confirm_candle["close"]
    distance_pips = abs(close - liquidity_level) / pip

    immediate = distance_pips <= IMMEDIATE_ENTRY_PIP_THRESHOLD

    if bias == "long":
        sl = liquidity_level - 5 * pip
    else:
        sl = liquidity_level + 5 * pip

    risk = abs(close - sl)
    if bias == "long":
        tp_low = close + 3 * risk
        tp_high = close + 4 * risk
    else:
        tp_low = close - 3 * risk
        tp_high = close - 4 * risk

    return {
        "immediate": immediate,
        "distance_pips": round(distance_pips, 1),
        "entry_zone": close if immediate else None,
        "sl": round(sl, 5),
        "tp_low": round(tp_low, 5),
        "tp_high": round(tp_high, 5),
    }


# ---------------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------------

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    resp = requests.post(url, data=payload, timeout=15)
    if resp.status_code != 200:
        print(f"  ! Telegram send failed: {resp.text}")


# ---------------------------------------------------------------------------
# MAIN PIPELINE PER PAIR
# ---------------------------------------------------------------------------

def process_pair(pair, state):
    pstate = get_pair_state(state, pair)
    pip = pip_size(pair)

    weekly = fetch_candles(pair, "1week", outputsize=60)
    time.sleep(8)
    daily = fetch_candles(pair, "1day", outputsize=30)
    time.sleep(8)
    h4 = fetch_candles(pair, "4h", outputsize=30)
    time.sleep(8)

    if not weekly or not daily or not h4:
        return

    latest_price = daily[-1]["close"]

    # --- STAGE: watching for weekly key area + engulfing (Rules 1 & 2) ---
    if pstate["stage"] == "watching_weekly":
        levels = find_weekly_key_levels(weekly)
        in_any_zone = any(price_in_zone(latest_price, lv["low"], lv["high"]) for lv in levels)
        if not in_any_zone:
            return

        prev, curr = weekly[-2], weekly[-1]
        bias = check_weekly_engulfing(prev, curr)
        if bias:
            pstate["stage"] = "weekly_confirmed"
            pstate["bias"] = bias
            pstate["weekly_confirm_candle"] = curr
            send_telegram(
                f"📍 *{pair}* — Weekly key-area confirmation ({bias.upper()})\n"
                f"Watching for retest into confirmation candle's body before moving to Daily."
            )
        return

    # --- STAGE: waiting for retest into weekly confirmation candle body (Rule 3) ---
    if pstate["stage"] == "weekly_confirmed":
        confirm = pstate["weekly_confirm_candle"]
        if price_retested_body(confirm, latest_price):
            pstate["stage"] = "daily_watch"
            send_telegram(f"🔁 *{pair}* — Retest into weekly confirmation zone. Switching to Daily.")
        return

    # --- STAGE: watching daily BSL/SSL sweep (Rule 4) ---
    if pstate["stage"] == "daily_watch":
        levels = find_daily_liquidity_levels(daily, weeks=DAILY_LOOKBACK_WEEKS)
        swept_level = check_daily_sweep(daily[-1], levels, pstate["bias"])
        if swept_level:
            pstate["stage"] = "h4_watch"
            pstate["daily_liquidity_level"] = swept_level
            send_telegram(f"⚡ *{pair}* — Daily liquidity swept at {swept_level:.5f}. Switching to H4.")
        return

    # --- STAGE: watching for H4 confirmation (Rule 5) ---
    if pstate["stage"] == "h4_watch":
        level_used = check_h4_confirmation(h4, pstate["daily_liquidity_level"], pstate["bias"],
                                            tolerance_pips=10, pip=pip)
        if level_used:
            confirm_candle = h4[-1]
            plan = compute_trade_plan(confirm_candle, level_used, pstate["bias"], pip)
            pstate["stage"] = "h4_confirmed"
            pstate["sl"] = plan["sl"]
            pstate["tp"] = [plan["tp_low"], plan["tp_high"]]

            if plan["immediate"]:
                pstate["stage"] = "in_trade"
                pstate["entry"] = confirm_candle["close"]
                send_telegram(
                    f"🚨 *{pair}* — ENTRY ({pstate['bias'].upper()})\n"
                    f"Entry: {confirm_candle['close']:.5f} (immediate — {plan['distance_pips']} pips from liquidity)\n"
                    f"SL: {plan['sl']:.5f}\n"
                    f"TP: {plan['tp_low']:.5f} – {plan['tp_high']:.5f}\n"
                    f"Move SL to breakeven at 1:1."
                )
            else:
                send_telegram(
                    f"⏳ *{pair}* — H4 confirmed but {plan['distance_pips']} pips from liquidity (>30).\n"
                    f"Waiting for retracement into entry zone before entering.\n"
                    f"Planned SL: {plan['sl']:.5f} | TP: {plan['tp_low']:.5f} – {plan['tp_high']:.5f}"
                )
        return

    # --- STAGE: waiting for retracement entry (>30 pip case) ---
    if pstate["stage"] == "h4_confirmed":
        confirm_candle = h4[-1]
        near_entry = abs(latest_price - confirm_candle["close"]) / pip <= IMMEDIATE_ENTRY_PIP_THRESHOLD
        if near_entry:
            pstate["stage"] = "in_trade"
            pstate["entry"] = latest_price
            send_telegram(
                f"🚨 *{pair}* — ENTRY on retracement ({pstate['bias'].upper()})\n"
                f"Entry: {latest_price:.5f}\n"
                f"SL: {pstate['sl']:.5f}\n"
                f"TP: {pstate['tp'][0]:.5f} – {pstate['tp'][1]:.5f}\n"
                f"Move SL to breakeven at 1:1."
            )
        return

    # --- STAGE: in trade - check breakeven ---
    if pstate["stage"] == "in_trade" and not pstate["breakeven_done"]:
        entry = pstate["entry"]
        sl = pstate["sl"]
        risk = abs(entry - sl)
        if pstate["bias"] == "long" and latest_price >= entry + risk:
            pstate["breakeven_done"] = True
            send_telegram(f"✅ *{pair}* — Price hit 1:1. Move SL to breakeven ({entry:.5f}).")
        elif pstate["bias"] == "short" and latest_price <= entry - risk:
            pstate["breakeven_done"] = True
            send_telegram(f"✅ *{pair}* — Price hit 1:1. Move SL to breakeven ({entry:.5f}).")
        return


def main():
    state = load_state()
    for pair in PAIRS:
        try:
            print(f"Checking {pair}...")
            process_pair(pair, state)
        except Exception as e:
            print(f"  ! Error processing {pair}: {e}")
        time.sleep(1)
    save_state(state)


if __name__ == "__main__":
    main()
