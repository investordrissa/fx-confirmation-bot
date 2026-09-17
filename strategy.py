from dataclasses import dataclass
from typing import Optional, Literal

Direction = Literal["BUY", "SELL"]


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    time: Optional[str] = None


@dataclass
class Zone:
    low: float
    high: float
    kind: str
    valid: bool = True
    direction: Optional[str] = None


@dataclass
class Setup:
    direction: Direction
    weekly_zone: Zone
    daily_liquidity: float
    entry: float
    stop_loss: float
    target_3R: float
    target_4R: float
    breakeven_at: float
    status: str


# ---------------------------------------------------------
# BASIC PRICE HELPERS
# ---------------------------------------------------------

def body_high(candle: Candle) -> float:
    return max(candle.open, candle.close)


def body_low(candle: Candle) -> float:
    return min(candle.open, candle.close)


def body_size(candle: Candle) -> float:
    return abs(candle.close - candle.open)


def is_bullish(candle: Candle) -> bool:
    return candle.close > candle.open


def is_bearish(candle: Candle) -> bool:
    return candle.close < candle.open


# ---------------------------------------------------------
# WEEKLY ENGULFING CONFIRMATION
# ---------------------------------------------------------

def weekly_bullish_engulfing(previous: Candle, current: Candle) -> bool:
    full_body_close_through = (
        is_bearish(previous)
        and is_bullish(current)
        and current.open <= previous.close
        and current.close >= previous.open
    )

    swept_and_closed_back = (
        current.low < previous.low
        and current.close >= (
            previous.low + (previous.high - previous.low) * 0.50
        )
    )

    return full_body_close_through or swept_and_closed_back


def weekly_bearish_engulfing(previous: Candle, current: Candle) -> bool:
    full_body_close_through = (
        is_bullish(previous)
        and is_bearish(current)
        and current.open >= previous.close
        and current.close <= previous.open
    )

    swept_and_closed_back = (
        current.high > previous.high
        and current.close <= (
            previous.high - (previous.high - previous.low) * 0.50
        )
    )

    return full_body_close_through or swept_and_closed_back


# ---------------------------------------------------------
# PRICE RETURN TO WEEKLY KEY AREA
# ---------------------------------------------------------

def price_in_zone(price: float, zone: Zone) -> bool:
    return zone.valid and zone.low <= price <= zone.high


def weekly_return_valid(price: float, weekly_zones: list) -> Optional[Zone]:
    for zone in weekly_zones:
        if price_in_zone(price, zone):
            return zone

    return None


# ---------------------------------------------------------
# DAILY LIQUIDITY
# ---------------------------------------------------------

def daily_bsl_ssl_swept(
    current_week_candles: list,
    previous_week_candles: list,
    direction: Direction,
) -> Optional[float]:

    candles = previous_week_candles + current_week_candles
    if not candles:
        return None

    if direction == "BUY":
        structural_high = candles[0].high
        reference_low = candles[0].low
        for c in candles[1:]:
            if c.low < reference_low:
                return reference_low
            if c.high > structural_high:
                structural_high = c.high
                reference_low = c.low
    else:
        structural_low = candles[0].low
        reference_high = candles[0].high
        for c in candles[1:]:
            if c.high > reference_high:
                return reference_high
            if c.low < structural_low:
                structural_low = c.low
                reference_high = c.high

    return None


# ---------------------------------------------------------
# H4 CONFIRMATION
# ---------------------------------------------------------

def decisive_h4_bullish_close(
    liquidity_swept: bool,
    displacement: bool,
    higher_high: bool,
    higher_low: bool,
    decisive_close: bool,
    minor_sr: bool,
) -> bool:
    return all([
        liquidity_swept,
        displacement,
        higher_high,
        higher_low,
        decisive_close,
        minor_sr,
    ])


def decisive_h4_bearish_close(
    liquidity_swept: bool,
    displacement: bool,
    lower_high: bool,
    lower_low: bool,
    decisive_close: bool,
    minor_sr: bool,
) -> bool:
    return all([
        liquidity_swept,
        displacement,
        lower_high,
        lower_low,
        decisive_close,
        minor_sr,
    ])


# ---------------------------------------------------------
# ENTRY DISTANCE RULE
# ---------------------------------------------------------

def entry_distance_action(
    entry: float,
    confirmation_price: float,
    pip_size: float,
) -> str:

    distance_pips = abs(entry - confirmation_price) / pip_size

    if distance_pips <= 55:
        return "ENTER"

    return "RETRACE_ZONE"


# ---------------------------------------------------------
# STOP LOSS
# ---------------------------------------------------------

def calculate_stop_loss(
    liquidity_level: float,
    direction: Direction,
    pip_size: float,
) -> float:

    five_pips = 5 * pip_size

    if direction == "BUY":
        return liquidity_level - five_pips

    return liquidity_level + five_pips


# ---------------------------------------------------------
# TARGETS
# ---------------------------------------------------------

def structural_liquidity(daily_all, direction, lookback_days=14):
    """
    Tracks the structural swing-high/low continuously across all daily
    history provided, and only returns it as valid daily liquidity if
    the swing's own reference candle formed within the last N days
    (lookback_days), matching "current or previous week" in spirit.
    """
    from datetime import datetime, timezone, timedelta
    if len(daily_all) < 2:
        return None
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    if direction == "BUY":
        structural_high = daily_all[0].high
        reference_low = daily_all[0].low
        reference_time = daily_all[0].time
        for c in daily_all[1:]:
            if c.low < reference_low:
                if reference_time and datetime.fromisoformat(reference_time) >= cutoff:
                    return reference_low
                structural_high = c.high
                reference_low = c.low
                reference_time = c.time
                continue
            if c.high > structural_high:
                structural_high = c.high
                reference_low = c.low
                reference_time = c.time
    else:
        structural_low = daily_all[0].low
        reference_high = daily_all[0].high
        reference_time = daily_all[0].time
        for c in daily_all[1:]:
            if c.high > reference_high:
                if reference_time and datetime.fromisoformat(reference_time) >= cutoff:
                    return reference_high
                structural_low = c.low
                reference_high = c.high
                reference_time = c.time
                continue
            if c.low < structural_low:
                structural_low = c.low
                reference_high = c.high
                reference_time = c.time

    return None


def calculate_targets(
    entry: float,
    stop_loss: float,
    direction: Direction,
):

    risk = abs(entry - stop_loss)

    if direction == "BUY":
        target_3r = entry + (risk * 3)
        target_4r = entry + (risk * 4)
    else:
        target_3r = entry - (risk * 3)
        target_4r = entry - (risk * 4)

    breakeven = entry + risk if direction == "BUY" else entry - risk

    return target_3r, target_4r, breakeven


# ---------------------------------------------------------
# COMPLETE SETUP CHECK
# ---------------------------------------------------------

def evaluate_setup(
    price: float,
    weekly_zones: list,
    direction: Direction,
    daily_liquidity: float,
    h4_confirmation_price: float,
    pip_size: float,
) -> Optional[Setup]:

    weekly_zone = weekly_return_valid(price, weekly_zones)

    if weekly_zone is None:
        return None

    action = entry_distance_action(
        price,
        h4_confirmation_price,
        pip_size,
    )

    if action not in ("ENTER", "RETRACE_ZONE"):
        return None

    stop_loss = calculate_stop_loss(
        daily_liquidity,
        direction,
        pip_size,
    )

    target_3r, target_4r, breakeven = calculate_targets(
        price,
        stop_loss,
        direction,
    )

    return Setup(
        direction=direction,
        weekly_zone=weekly_zone,
        daily_liquidity=daily_liquidity,
        entry=price,
        stop_loss=stop_loss,
        target_3R=target_3r,
        target_4R=target_4r,
        breakeven_at=breakeven,
        status=action,
    )


# ---------------------------------------------------------
# CAPPED RETRACEMENT ENTRY (Rule 6)
# ---------------------------------------------------------

def capped_retrace_entry(liquidity_level: float, direction: Direction, pip_size: float) -> float:
    """
    When the H4 confirmation candle closes more than 55 pips away from the
    swept liquidity level, we don't chase price -- we wait for a
    retracement back to exactly 55 pips from the liquidity level, which
    becomes the entry.
    """
    cap = 55 * pip_size
    if direction == "BUY":
        return liquidity_level + cap
    return liquidity_level - cap
