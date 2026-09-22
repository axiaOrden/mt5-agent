"""Phase 1.7 tests: Chikou directional confirmation semantics.

The Chikou span plots the current close against the price structure 26 bars
back. These tests craft frames where the current close is clearly above,
below, or entangled with the historical structure at ``ref = last - 26``.

n = 110 so that ``ref = 83`` and the historical Kumo at ``ref`` (Senkou B
needs 52 bars ending at ``ref - 26 = 57``) is fully formed.
"""

import numpy as np
import pandas as pd

from src.analysis.market_state import MarketStateAnalyzer
from src.indicators.ichimoku import ichimoku

N = 110


def _frame(highs, lows, closes) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=N, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "time": idx,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
        }
    )


def _chikou(highs, lows, closes):
    df = _frame(highs, lows, closes)
    result = ichimoku(df)
    return MarketStateAnalyzer._chikou(df, result, len(df) - 1)


def test_chikou_bullish_clean_confirmation():
    """Current close far above the historical structure at ref -> BULLISH, clean."""
    highs = np.full(N, 100.0)
    lows = np.full(N, 99.0)
    closes = np.full(N, 99.5)
    closes[-26:] = np.linspace(100.0, 200.0, 26)
    highs[-26:] = closes[-26:] + 1.0
    lows[-26:] = closes[-26:] - 1.0
    chikou, obstructed = _chikou(highs, lows, closes)
    assert chikou == "BULLISH"
    assert obstructed is False


def test_chikou_bearish_clean_confirmation():
    """Current close far below the historical structure at ref -> BEARISH, clean."""
    highs = np.full(N, 200.0)
    lows = np.full(N, 199.0)
    closes = np.full(N, 199.5)
    closes[-26:] = np.linspace(200.0, 100.0, 26)
    highs[-26:] = closes[-26:] + 1.0
    lows[-26:] = closes[-26:] - 1.0
    chikou, obstructed = _chikou(highs, lows, closes)
    assert chikou == "BEARISH"
    assert obstructed is False


def test_chikou_bullish_but_obstructed_by_kumo():
    """Current close above the historical candle high but inside the historical
    Kumo -> directional but obstructed."""
    highs = np.full(N, 100.0)
    lows = np.full(N, 99.0)
    closes = np.full(N, 99.5)
    # A huge high spike 26+ bars before ref inflates the historical Kumo at ref.
    highs[40] = 500.0
    closes[-26:] = np.linspace(100.0, 200.0, 26)  # close above ref high (100)
    highs[-26:] = closes[-26:] + 1.0
    lows[-26:] = closes[-26:] - 1.0
    chikou, obstructed = _chikou(highs, lows, closes)
    assert chikou == "BULLISH"
    assert obstructed is True


def test_chikou_neutral_inside_historical_range():
    """Current close inside the historical candle range -> NEUTRAL, obstructed."""
    highs = np.full(N, 100.0)
    lows = np.full(N, 99.0)
    closes = np.full(N, 99.5)
    chikou, obstructed = _chikou(highs, lows, closes)
    assert chikou == "NEUTRAL"
    assert obstructed is True
