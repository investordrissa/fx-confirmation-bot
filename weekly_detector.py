import strategy
from typing import List


def _body_high(c):
    return max(c.open, c.close)


def _body_low(c):
    return min(c.open, c.close)


def _bullish(c):
    return c.close > c.open


def _bearish(c):
    return c.close < c.open


def _range(c):
    return c.high - c.low


def _body_size(c):
    return abs(c.close - c.open)


def _impulsive(c):
    r = _range(c)
    if r <= 0:
        return False
    return (_body_size(c) / r) >= 0.60


def _fvg_zones(candles: List[strategy.Candle]):
    zones = []
    for i in range(2, len(candles)):
        a = candles[i - 2]
        c = candles[i]
        if c.low > a.high:
            zones.append(strategy.Zone(low=a.high, high=c.low, kind="FVG", valid=True, direction="BUY"))
        elif c.high < a.low:
            zones.append(strategy.Zone(low=c.high, high=a.low, kind="FVG", valid=True, direction="SELL"))
    return zones


SWING_ZONE_BUFFER_RATIO = 0.15  # buffer as a fraction of the swing candle's own range


def _swing_zones(candles: List[strategy.Candle]):
    zones = []
    for i in range(1, len(candles) - 1):
        prev_c = candles[i - 1]
        cur = candles[i]
        next_c = candles[i + 1]
        buffer = _range(cur) * SWING_ZONE_BUFFER_RATIO
        if cur.high > prev_c.high and cur.high > next_c.high:
            zones.append(strategy.Zone(low=cur.high - buffer, high=cur.high + buffer,
                                        kind="SWING_HIGH", valid=True, direction="SELL"))
        if cur.low < prev_c.low and cur.low < next_c.low:
            zones.append(strategy.Zone(low=cur.low - buffer, high=cur.low + buffer,
                                        kind="SWING_LOW", valid=True, direction="BUY"))
    return zones


def _order_block_zones(candles: List[strategy.Candle]):
    zones = []
    for i in range(len(candles) - 1):
        base = candles[i]
        move = candles[i + 1]
        if _bearish(base) and _bullish(move) and _impulsive(move):
            zones.append(strategy.Zone(low=base.low, high=base.high, kind="OB", valid=True, direction="BUY"))
        elif _bullish(base) and _bearish(move) and _impulsive(move):
            zones.append(strategy.Zone(low=base.low, high=base.high, kind="OB", valid=True, direction="SELL"))
    return zones


def _consolidation_zones(candles: List[strategy.Candle]):
    zones = []
    for i in range(2, len(candles) - 1):
        first = candles[i - 2]
        second = candles[i - 1]
        move = candles[i]
        candles_in_base = [first, second]
        base_high = max(c.high for c in candles_in_base)
        base_low = min(c.low for c in candles_in_base)
        base_range = base_high - base_low
        if base_range <= 0:
            continue
        contained = (
            _range(first) <= base_range * 1.25
            and _range(second) <= base_range * 1.25
        )
        if not contained:
            continue
        if _impulsive(move):
            direction = "BUY" if _bullish(move) else "SELL"
            zones.append(strategy.Zone(low=base_low, high=base_high, kind="ACCUMULATION", valid=True, direction=direction))
    return zones


def detect_weekly_zones(candles: List[strategy.Candle]):
    if not candles:
        return []
    zones = []
    zones.extend(_order_block_zones(candles))
    zones.extend(_consolidation_zones(candles))
    zones.extend(_fvg_zones(candles))
    zones.extend(_swing_zones(candles))
    return zones


def zones_at_price(candles, price):
    zones = detect_weekly_zones(candles)
    return [
        zone
        for zone in zones
        if zone.valid and zone.low <= price <= zone.high
    ]
