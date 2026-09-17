import strategy
from typing import List, Optional, Tuple


def candle_body(candle):
    return (
        min(float(candle.open), float(candle.close)),
        max(float(candle.open), float(candle.close)),
    )


def price_in_body(price: float, candle) -> bool:
    body_low, body_high = candle_body(candle)
    return body_low <= float(price) <= body_high


def candle_touched_body(candle, confirmation_candle) -> bool:
    body_low, body_high = candle_body(confirmation_candle)
    candle_low = float(candle.low)
    candle_high = float(candle.high)

    return candle_low <= body_high and candle_high >= body_low


def find_body_retest(
    candles: List[strategy.Candle],
    confirmation_index: int,
) -> Optional[Tuple[int, float, float]]:

    if not candles:
        return None

    if confirmation_index < 0:
        confirmation_index = len(candles) + confirmation_index

    if confirmation_index < 0 or confirmation_index >= len(candles):
        return None

    confirmation_candle = candles[confirmation_index]
    body_low, body_high = candle_body(confirmation_candle)

    for i in range(confirmation_index + 1, len(candles)):
        if candle_touched_body(candles[i], confirmation_candle):
            return i, body_low, body_high

    return None


def body_retest_at_price(
    candles: List[strategy.Candle],
    confirmation_index: int,
    price: float,
) -> bool:

    if not candles:
        return False

    if confirmation_index < 0:
        confirmation_index = len(candles) + confirmation_index

    if confirmation_index < 0 or confirmation_index >= len(candles):
        return False

    return price_in_body(price, candles[confirmation_index])


def weekly_pipeline_ready(
    candles: List[strategy.Candle],
    confirmation_index: int,
    current_price: float,
) -> bool:

    return body_retest_at_price(
        candles,
        confirmation_index,
        current_price,
    )


def describe_body_retest(
    candles: List[strategy.Candle],
    confirmation_index: int,
    current_price: float,
) -> dict:

    if not candles:
        return {
            "ready": False,
            "reason": "NO_WEEKLY_CANDLES",
        }

    if confirmation_index < 0:
        confirmation_index = len(candles) + confirmation_index

    if confirmation_index < 0 or confirmation_index >= len(candles):
        return {
            "ready": False,
            "reason": "INVALID_CONFIRMATION_INDEX",
        }

    confirmation = candles[confirmation_index]
    body_low, body_high = candle_body(confirmation)

    ready = body_retest_at_price(
        candles,
        confirmation_index,
        current_price,
    )

    return {
        "ready": ready,
        "confirmation_index": confirmation_index,
        "body_low": body_low,
        "body_high": body_high,
        "current_price": float(current_price),
        "reason": (
            "PRICE_RETURNED_TO_WEEKLY_BODY"
            if ready
            else "WAITING_FOR_WEEKLY_BODY_RETEST"
        ),
    }
