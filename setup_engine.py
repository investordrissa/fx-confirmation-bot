from dataclasses import dataclass
from dataclasses import dataclass
from typing import Optional

import strategy


@dataclass
class EngineResult:
    direction: str
    setup: Optional[str]
    reason: str


class SetupEngine:

    def evaluate(
        self,
        price: float,
        weekly_zones: list[strategy.Zone],
        direction: str,
        daily_liquidity: float,
        h4_confirmation_price: float,
        pip_size: float,
    ):
        """
        Final setup calculation.

        All trading calculations remain in strategy.py.
        """

        return strategy.evaluate_setup(
            price=price,
            weekly_zones=weekly_zones,
            direction=direction,
            daily_liquidity=daily_liquidity,
            h4_confirmation_price=h4_confirmation_price,
            pip_size=pip_size,
        )

    def weekly_confirmation(
        self,
        previous: strategy.Candle,
        current: strategy.Candle,
        direction: str,
    ) -> bool:

        if direction == "BUY":
            return strategy.weekly_bullish_engulfing(
                previous,
                current,
            )

        if direction == "SELL":
            return strategy.weekly_bearish_engulfing(
                previous,
                current,
            )

        return False

    def daily_liquidity(
        self,
        current_week: list[strategy.Candle],
        previous_week: list[strategy.Candle],
        direction: str,
    ) -> Optional[float]:

        return strategy.daily_bsl_ssl_swept(
            current_week_candles=current_week,
            previous_week_candles=previous_week,
            direction=direction,
        )

    def h4_confirmation(
        self,
        direction: str,
        liquidity_swept: bool,
        displacement: bool,
        structure_1: bool,
        structure_2: bool,
        decisive_close: bool,
        minor_sr: bool,
    ) -> bool:

        if direction == "BUY":
            return strategy.decisive_h4_bullish_close(
                liquidity_swept=liquidity_swept,
                displacement=displacement,
                higher_high=structure_1,
                higher_low=structure_2,
                decisive_close=decisive_close,
                minor_sr=minor_sr,
            )

        if direction == "SELL":
            return strategy.decisive_h4_bearish_close(
                liquidity_swept=liquidity_swept,
                displacement=displacement,
                lower_high=structure_1,
                lower_low=structure_2,
                decisive_close=decisive_close,
                minor_sr=minor_sr,
            )

        return False
