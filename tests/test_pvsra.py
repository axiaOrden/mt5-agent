from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.context import context_as_of, context_for_event
from src.pvsra import (
    CandleDirection, PVSRAClassification as C, VolumeSource,
    analyze_pvsra, classify_pvsra, pvsra_as_of,
)


START = pd.Timestamp("2026-01-05 00:00:00Z")


def bars(n=30, *, real=False):
    x = np.arange(n)
    close = 100 + np.sin(x / 3) * 2 + x * .05
    open_ = close - .2
    frame = pd.DataFrame({
        "time": pd.date_range(START, periods=n, freq="15min"),
        "open": open_, "high": close + 1, "low": close - 1, "close": close,
        "tick_volume": np.full(n, 100.0),
        "real_volume": np.full(n, 50.0) if real else np.zeros(n),
    })
    return frame


@pytest.mark.parametrize("volume,expected", [
    (119.99, C.NORMAL),
    (120.0, C.ABOVE_AVERAGE),
    (125.0, C.ABOVE_AVERAGE),
    (200.0, C.ABOVE_AVERAGE),  # no secondary expansion
    (220.0, C.ABOVE_AVERAGE),
])
def test_volume_thresholds_without_climax_secondary(volume, expected):
    assert classify_pvsra(volume, 100, 10, 10, 10, 10) == expected


def test_climax_at_exact_volume_and_spread_boundaries():
    assert classify_pvsra(200, 100, 15, 10, 10, 10) == C.CLIMAX


def test_climax_at_exact_displacement_boundary():
    assert classify_pvsra(200, 100, 10, 10, 15, 10) == C.CLIMAX


def test_climax_by_spread_or_vwap_and_precedes_above_average():
    assert classify_pvsra(210, 100, 16, 10, 10, 10) == C.CLIMAX
    assert classify_pvsra(210, 100, 10, 10, 16, 10) == C.CLIMAX


@pytest.mark.parametrize("open_,close,direction", [
    (100, 101, CandleDirection.BULLISH),
    (101, 100, CandleDirection.BEARISH),
    (100, 100, CandleDirection.NEUTRAL),
])
def test_candle_direction(open_, close, direction):
    frame = bars()
    frame.loc[len(frame)-1, ["open", "close"]] = [open_, close]
    result = analyze_pvsra(frame, "M15", daily_opens=pd.Series([START]))
    assert result.candle_direction == direction


def test_volume_source_prefers_usable_real_then_tick():
    assert analyze_pvsra(bars(real=True), "M15", daily_opens=pd.Series([START])).volume_source == VolumeSource.REAL_VOLUME
    assert analyze_pvsra(bars(real=False), "M15", daily_opens=pd.Series([START])).volume_source == VolumeSource.TICK_VOLUME


def test_insufficient_history_is_unavailable():
    result = analyze_pvsra(bars(19), "M15", daily_opens=pd.Series([START]))
    assert result.classification == C.UNAVAILABLE
    assert result.volume_ma is None


def test_missing_or_zero_volume_is_unavailable():
    missing = bars().drop(columns=["tick_volume", "real_volume"])
    zero = bars()
    zero[["tick_volume", "real_volume"]] = 0
    for frame in (missing, zero):
        result = analyze_pvsra(frame, "M15", daily_opens=pd.Series([START]))
        assert result.classification == C.UNAVAILABLE
        assert result.volume_source == VolumeSource.UNAVAILABLE
        assert result.volume is None


def test_unavailable_broker_day_boundaries_make_vwap_unavailable():
    result = analyze_pvsra(bars(), "M15")
    assert result.classification == C.UNAVAILABLE
    assert result.vwap is None
    assert result.vwap_displacement is None


def test_historical_target_ignores_future_high_volume_bar():
    original = bars(25)
    target = original.time.iloc[-1]
    before = analyze_pvsra(original, "M15", bar_open_time=target,
                           daily_opens=pd.Series([START]))
    future = original.iloc[-1].copy()
    future["time"] = target + pd.Timedelta(minutes=15)
    future["tick_volume"] = 1_000_000
    appended = pd.concat([original, future.to_frame().T], ignore_index=True)
    after = analyze_pvsra(appended, "M15", bar_open_time=target,
                          daily_opens=pd.Series([START]))
    assert before == after


def test_as_of_excludes_forming_candle():
    frame = bars(25)
    forming = frame.time.iloc[-1]
    as_of = forming + pd.Timedelta(minutes=10)
    result = pvsra_as_of(
        frame, "M15", as_of,
        daily_bars=pd.DataFrame({"time": pd.Series([START - pd.Timedelta(days=1)])}),
    )
    assert result.bar_open_time == frame.time.iloc[-2].to_pydatetime()


def test_determinism():
    frame = bars()
    args = dict(timeframe="M15", daily_opens=pd.Series([START]))
    assert analyze_pvsra(frame, **args) == analyze_pvsra(frame, **args)


def _context_histories():
    end = datetime(2026, 4, 10, 12, tzinfo=timezone.utc)
    deltas = {"M15": timedelta(minutes=15), "H1": timedelta(hours=1),
              "H4": timedelta(hours=4), "D1": timedelta(days=1)}
    result = {}
    for tf, delta in deltas.items():
        n = 180
        x = np.arange(n)
        close = 100 + np.sin(x / 2.3) * 8 + x * .015
        open_ = close + np.cos(x / 1.7)
        result[tf] = pd.DataFrame({
            "time": pd.to_datetime([end - delta * (n-i) for i in range(n)], utc=True),
            "open": open_, "high": np.maximum(open_, close)+2,
            "low": np.minimum(open_, close)-2, "close": close,
            "tick_volume": 10+x%7, "real_volume": 0,
        })
    return result, end


def test_context_attaches_persistent_event_candle_pvsra():
    histories, end = _context_histories()
    current = context_as_of(histories, "TEST", "M15", end)
    historical = context_for_event(histories, "TEST", "M15", current.cloudgazer_transition)
    assert historical.event_pvsra is not None
    assert historical.event_pvsra.bar_open_time == current.cloudgazer_transition.bar_open_time

    later = {key: value.copy() for key, value in histories.items()}
    future = later["M15"].iloc[-1].copy()
    future["time"] = pd.Timestamp(end)
    future["tick_volume"] = 999_999
    later["M15"] = pd.concat([later["M15"], future.to_frame().T], ignore_index=True)
    repeated = context_for_event(later, "TEST", "M15", current.cloudgazer_transition)
    assert repeated.event_pvsra == historical.event_pvsra
