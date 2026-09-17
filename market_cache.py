import time
from dataclasses import dataclass
from typing import Dict, Tuple

from data_feed import get_candles
from market_adapter import dataframe_to_candles
from config import TIMEFRAMES, OUTPUT_SIZE


@dataclass
class CachedData:
    candles: list
    fetched_at: float


class MarketCache:
    def __init__(self):
        self._cache: Dict[Tuple[str, str], CachedData] = {}

    def get(self, pair: str, timeframe: str, max_age: int):
        key = (pair, timeframe)
        now = time.time()

        item = self._cache.get(key)

        if item is not None:
            age = now - item.fetched_at

            if age < max_age:
                return item.candles

        interval = TIMEFRAMES[timeframe]

        raw = get_candles(
            pair,
            interval,
            OUTPUT_SIZE,
        )

        # data_feed.get_candles() returns a pandas DataFrame; convert to
        # the list[Candle] the rest of the pipeline expects.
        candles = dataframe_to_candles(raw) if hasattr(raw, "empty") else raw

        self._cache[key] = CachedData(
            candles=candles,
            fetched_at=now,
        )

        return candles

    def get_weekly(self, pair: str):
        return self.get(pair, "weekly", 3600)

    def get_daily(self, pair: str):
        return self.get(pair, "daily", 1800)

    def get_h4(self, pair: str):
        return self.get(pair, "4h", 300)

    def clear(self):
        self._cache.clear()

    def status(self):
        now = time.time()
        result = {}
        for (pair, timeframe), item in self._cache.items():
            result[f"{pair}:{timeframe}"] = round(now - item.fetched_at, 1)
        return result
