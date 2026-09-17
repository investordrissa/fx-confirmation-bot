import pandas as pd
from strategy import Candle


def dataframe_to_candles(df: pd.DataFrame) -> list[Candle]:
    if df is None or df.empty:
        return []

    required = {"open", "high", "low", "close"}

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing candle columns: {sorted(missing)}"
        )

    candles = []

    for _, row in df.iterrows():
        candles.append(
            Candle(
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
        )

    return candles


def latest_price(df: pd.DataFrame) -> float:
    if df is None or df.empty:
        raise ValueError("No price data available")

    return float(df.iloc[-1]["close"])
