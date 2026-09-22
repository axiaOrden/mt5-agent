"""Unit tests for market-state classification (deterministic, no LLM)."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.market_state import MarketStateAnalyzer, MIN_BARS


def _trend_frame(n: int, drift: float, vol: float = 0.05, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    steps = rng.normal(drift, vol, size=n)
    close = 100.0 * np.exp(np.cumsum(steps))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, size=n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, size=n)))
    return pd.DataFrame(
        {"time": idx, "open": open_, "high": high, "low": low, "close": close}
    )


def _flat_frame(n: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "time": idx,
            "open": np.full(n, 100.0),
            "high": np.full(n, 100.0),
            "low": np.full(n, 100.0),
            "close": np.full(n, 100.0),
        }
    )


def test_strong_uptrend_is_established_bullish():
    df = _trend_frame(300, drift=0.008, vol=0.01, seed=1)
    state = MarketStateAnalyzer().analyze(df, "XAUUSDm", "H1")
    assert state.direction == "BULLISH"
    assert state.condition == "ESTABLISHED"
    assert state.price_vs_kumo == "ABOVE"
    assert state.tenkan_vs_kijun == "BULLISH"
    assert state.projected_kumo == "BULLISH"
    assert state.chikou == "BULLISH"
    assert state.chikou_obstructed is False
    assert state.kijun_slope == "RISING"
    assert state.score >= 3


def test_strong_downtrend_is_established_bearish():
    df = _trend_frame(300, drift=-0.008, vol=0.01, seed=2)
    state = MarketStateAnalyzer().analyze(df, "EURUSDm", "H1")
    assert state.direction == "BEARISH"
    assert state.condition == "ESTABLISHED"
    assert state.price_vs_kumo == "BELOW"
    assert state.tenkan_vs_kijun == "BEARISH"
    assert state.projected_kumo == "BEARISH"
    assert state.chikou == "BEARISH"
    assert state.score <= -3


def test_flat_market_is_neutral_transition():
    df = _flat_frame(300)
    state = MarketStateAnalyzer().analyze(df, "EURUSDm", "H1")
    assert state.direction == "NEUTRAL"
    assert state.condition == "TRANSITION"
    assert state.score == 0


def test_insufficient_bars_is_neutral():
    df = _trend_frame(MIN_BARS - 1, drift=0.004)
    state = MarketStateAnalyzer().analyze(df, "XAUUSDm", "H1")
    assert state.direction == "NEUTRAL"
    assert state.condition == "TRANSITION"
    assert state.price_vs_kumo == "N/A"


def test_contradictory_components_are_not_established_trend():
    """Price below Kumo but every structural component bullish.

    Phase 1.7 correction: this must NOT be classified as an established
    bullish market. It is a NEUTRAL direction with a REVERSAL_ATTEMPT
    condition (an emerging bullish attempt against a bearish price position).
    """
    direction, condition = MarketStateAnalyzer._classify(
        price_vs_kumo="BELOW",
        tenkan_vs_kijun="BULLISH",
        projected_kumo="BULLISH",
        chikou="BULLISH",
        kijun_slope="RISING",
    )
    assert direction == "NEUTRAL"
    assert condition == "REVERSAL_ATTEMPT"


def test_price_above_with_bearish_majority_is_reversal_attempt():
    direction, condition = MarketStateAnalyzer._classify(
        price_vs_kumo="ABOVE",
        tenkan_vs_kijun="BEARISH",
        projected_kumo="BEARISH",
        chikou="BEARISH",
        kijun_slope="FALLING",
    )
    assert direction == "NEUTRAL"
    assert condition == "REVERSAL_ATTEMPT"


def test_price_inside_kumo_is_transition():
    direction, condition = MarketStateAnalyzer._classify(
        price_vs_kumo="INSIDE",
        tenkan_vs_kijun="BULLISH",
        projected_kumo="BULLISH",
        chikou="BULLISH",
        kijun_slope="RISING",
    )
    assert direction == "NEUTRAL"
    assert condition == "TRANSITION"


def test_contradictory_components_are_mixed():
    direction, condition = MarketStateAnalyzer._classify(
        price_vs_kumo="ABOVE",
        tenkan_vs_kijun="BEARISH",
        projected_kumo="BEARISH",
        chikou="BULLISH",
        kijun_slope="RISING",
    )
    assert direction == "NEUTRAL"
    assert condition == "MIXED"


def test_established_requires_no_opposing_votes():
    direction, condition = MarketStateAnalyzer._classify(
        price_vs_kumo="ABOVE",
        tenkan_vs_kijun="BULLISH",
        projected_kumo="BULLISH",
        chikou="BEARISH",
        kijun_slope="RISING",
    )
    assert direction == "BULLISH"
    assert condition == "TRANSITION"  # one opposing vote -> not ESTABLISHED


def test_analyze_multi_builds_timeframes():
    df = _trend_frame(300, drift=0.008, vol=0.01, seed=3)
    analyzer = MarketStateAnalyzer()
    market = analyzer.analyze_multi({"M15": df, "H1": df}, "XAUUSDm")
    assert set(market.timeframes) == {"M15", "H1"}
    assert market.state_for("H1").direction == "BULLISH"
    assert market.state_for("M15").direction == "BULLISH"


def test_kumo_thickness_is_atr_normalized():
    df = _trend_frame(300, drift=0.008, vol=0.01, seed=4)
    state = MarketStateAnalyzer().analyze(df, "XAUUSDm", "H1")
    assert state.kumo_thickness_atr is not None
    assert state.kumo_thickness_atr > 0


def test_candle_time_is_latest_bar():
    df = _trend_frame(300, drift=0.008, vol=0.01, seed=5)
    state = MarketStateAnalyzer().analyze(df, "XAUUSDm", "H1")
    assert state.candle_time == df["time"].iloc[-1].to_pydatetime()
    assert state.candle_closed is True


def test_broker_now_filters_forming_bar():
    """When broker_now is supplied, a forming last bar is excluded."""
    df = _trend_frame(300, drift=0.008, vol=0.01, seed=6)
    last = df["time"].iloc[-1]
    # broker_now is 5 minutes into the last H1 bar -> it is still forming.
    broker_now = (last + pd.Timedelta(minutes=5)).to_pydatetime()
    state = MarketStateAnalyzer().analyze(df, "XAUUSDm", "H1", broker_now=broker_now)
    assert state.candle_time == df["time"].iloc[-2].to_pydatetime()
    assert state.candle_closed is True
