import strategy
from typing import List, Optional


LOOKBACK = 10           # candles used to compute average body size
DISPLACEMENT_MULT = 1.5  # candle body must be 1.5x average to count as displacement
SWEEP_LOOKBACK = 3       # how many recent candles can count as "swept" the level
DECISIVE_CLOSE_RATIO = 0.65  # close must sit in the outer 65% of the candle's range,
                              # in the direction of the move, to count as decisive


def _avg_body(candles: List[strategy.Candle], end_index: int, lookback: int = LOOKBACK) -> float:
    start = max(0, end_index - lookback)
    window = candles[start:end_index]
    if not window:
        return 0.0
    return sum(strategy.body_size(c) for c in window) / len(window)


def _displacement(candles: List[strategy.Candle], idx: int) -> bool:
    avg = _avg_body(candles, idx)
    if avg == 0:
        return False
    return strategy.body_size(candles[idx]) >= DISPLACEMENT_MULT * avg


def _liquidity_swept(candles: List[strategy.Candle], idx: int, liquidity_price: float,
                      direction: str) -> bool:
    # Unlimited lookback: once the level is swept, it stays "swept" for as
    # long as we're watching for H4 confirmation -- no candle-count expiry,
    # since key levels don't expire in this strategy.
    window = candles[:idx + 1]
    if direction == "BUY":
        return any(c.low <= liquidity_price for c in window)
    return any(c.high >= liquidity_price for c in window)


def _structure(candles: List[strategy.Candle], idx: int, direction: str):
    """
    Returns (structure_1, structure_2) i.e. (higher_high, higher_low) for BUY
    or (lower_high, lower_low) for SELL, comparing the confirmation candle
    against the recent swing formed by the preceding candles.
    """
    start = max(0, idx - LOOKBACK)
    prior = candles[start:idx]
    if not prior:
        return False, False

    c = candles[idx]
    recent_high = max(p.high for p in prior)
    recent_low = min(p.low for p in prior)

    # Judged by close, not wick: the sweep candle's wick is expected to
    # push through the recent high/low (fully or partially) -- that's the
    # sweep itself. What confirms structure is where it closes.
    if direction == "BUY":
        higher_high = c.close > recent_high
        higher_low = c.close >= recent_low
        return higher_high, higher_low

    lower_high = c.close <= recent_high
    lower_low = c.close < recent_low
    return lower_high, lower_low


def _decisive_close(candle: strategy.Candle, direction: str) -> bool:
    rng = candle.high - candle.low
    if rng <= 0:
        return False

    if direction == "BUY":
        if not strategy.is_bullish(candle):
            return False
        return (candle.close - candle.low) / rng >= DECISIVE_CLOSE_RATIO

    if not strategy.is_bearish(candle):
        return False
    return (candle.high - candle.close) / rng >= DECISIVE_CLOSE_RATIO


MINOR_SR_PERIOD = 5


def _find_recent_pivot(candles, idx, period, kind):
    for p in range(idx - period, period - 1, -1):
        start, end = p - period, p + period
        if end > idx:
            continue
        candidate = candles[p]
        if kind == "high":
            if all(candidate.high > candles[k].high for k in range(start, end + 1) if k != p):
                return candidate.high
        else:
            if all(candidate.low < candles[k].low for k in range(start, end + 1) if k != p):
                return candidate.low
    return None


def minor_sr_broken(candles, idx, direction):
    """
    Short-term (5-candle) pivot support/resistance, matching the S&R TFlab
    indicator's Short Term Minor line. Checks whether the most recent
    confirmed pivot, opposing the trade direction, has been broken by the
    current candle's BODY CLOSE (not wick).
    """
    if idx < MINOR_SR_PERIOD * 2:
        return False
    if direction == "BUY":
        pivot = _find_recent_pivot(candles, idx, MINOR_SR_PERIOD, "high")
        return pivot is not None and candles[idx].close > pivot
    else:
        pivot = _find_recent_pivot(candles, idx, MINOR_SR_PERIOD, "low")
        return pivot is not None and candles[idx].close < pivot


def detect_h4_confirmation(
    candles: List[strategy.Candle],
    liquidity_price: float,
    direction: str,
    idx: Optional[int] = None,
) -> dict:
    """
    Computes the raw H4 confirmation signals from candles. Returns a dict
    with each component signal plus "confirmation_price" (the close of the
    confirming candle) for use by setup_engine.SetupEngine.h4_confirmation.
    """
    idx = len(candles) - 1 if idx is None else idx

    if idx < 3 or idx >= len(candles):
        return {"confirmed": False, "reason": "INSUFFICIENT_H4_CANDLES"}

    liquidity_swept = _liquidity_swept(candles, idx, liquidity_price, direction)
    displacement = _displacement(candles, idx)
    structure_1, structure_2 = _structure(candles, idx, direction)
    decisive_close = _decisive_close(candles[idx], direction)
    minor_sr = minor_sr_broken(candles, idx, direction)

    return {
        "liquidity_swept": liquidity_swept,
        "displacement": displacement,
        "structure_1": structure_1,
        "structure_2": structure_2,
        "decisive_close": decisive_close,
        "minor_sr": minor_sr,
        "confirmation_price": candles[idx].close,
        "index": idx,
    }
