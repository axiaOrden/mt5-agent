from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.analysis.market_state import MarketStateAnalyzer
from src.context import (
    Alignment, Direction, TimeframeContext, TimeframeRole,
    cloudgazer_alignment, context_as_of, context_for_event,
    direction_for_event, relevant_timeframes, structural_alignment,
)
from src.mt5.closure import bar_duration, filter_closed_bars
from src.signals.cloudgazer import replay_cloudgazer
from src.signals.models import CloudgazerState, EventType
from src.signals.vwap_events import broker_session_anchors


END = datetime(2026, 4, 10, 12, tzinfo=timezone.utc)
DELTAS = {
    "M15": timedelta(minutes=15), "H1": timedelta(hours=1),
    "H4": timedelta(hours=4), "D1": timedelta(days=1),
}


def history(timeframe, n=180, end=END):
    delta = DELTAS[timeframe]
    times = [end - delta * (n - i) for i in range(n)]
    x = np.arange(n)
    close = 100 + np.sin(x / 2.3) * 8 + x * 0.015
    open_ = close + np.cos(x / 1.7)
    return pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "open": open_, "high": np.maximum(open_, close) + 2,
        "low": np.minimum(open_, close) - 2, "close": close,
        "tick_volume": 10 + x % 7, "spread": 1, "real_volume": 0,
    })


def histories():
    return {tf: history(tf) for tf in DELTAS}


@pytest.mark.parametrize("event,market,expected", [
    (EventType.VWAP_CROSS_BULLISH, "BULLISH", Alignment.ALIGNED),
    (EventType.VWAP_CROSS_BULLISH, "BEARISH", Alignment.OPPOSED),
    (EventType.VWAP_CROSS_BULLISH, "NEUTRAL", Alignment.NEUTRAL),
    (EventType.TK_CROSS_BEARISH, "BEARISH", Alignment.ALIGNED),
    (EventType.TK_CROSS_BEARISH, "BULLISH", Alignment.OPPOSED),
    (EventType.TK_CROSS_BEARISH, "NEUTRAL", Alignment.NEUTRAL),
])
def test_structural_alignment(event, market, expected):
    assert structural_alignment(direction_for_event(event), market) == expected


def test_engulfing_has_no_state_direction():
    assert direction_for_event(EventType.BULLISH_ENGULFING) is None
    assert direction_for_event(EventType.BEARISH_ENGULFING) is None


def test_cloudgazer_alignment_rules():
    assert cloudgazer_alignment(Direction.BULLISH, CloudgazerState.LONG) == Alignment.ALIGNED
    assert cloudgazer_alignment(Direction.BULLISH, CloudgazerState.SHORT) == Alignment.OPPOSED
    assert cloudgazer_alignment(Direction.BEARISH, CloudgazerState.SHORT) == Alignment.ALIGNED
    assert cloudgazer_alignment(Direction.BEARISH, CloudgazerState.LONG) == Alignment.OPPOSED
    assert cloudgazer_alignment(Direction.BEARISH, CloudgazerState.FLAT) == Alignment.NEUTRAL


def test_condition_is_preserved_as_an_independent_fact():
    common = dict(
        timeframe="H1", role=TimeframeRole.INTERMEDIATE, market_direction="BEARISH",
        market_candle_time=None, cloudgazer_state=CloudgazerState.SHORT,
        structural_alignment=Alignment.OPPOSED, cloudgazer_alignment=Alignment.OPPOSED,
        latest_state_event=None, latest_state_event_time=None, state_event_age_bars=None,
        recent_state_changes=0, observed_bars=20,
    )
    established = TimeframeContext(market_condition="ESTABLISHED", **common)
    reversal = TimeframeContext(market_condition="REVERSAL_ATTEMPT", **common)
    assert established != reversal
    assert established.market_condition == "ESTABLISHED"
    assert reversal.market_condition == "REVERSAL_ATTEMPT"


def test_timeframe_relationships_support_non_m15_events():
    assert relevant_timeframes("M15") == ("M15", "H1", "H4", "D1")
    assert relevant_timeframes("H1") == ("H1", "H4", "D1")
    assert relevant_timeframes("H4") == ("H4", "D1")


def test_context_exposes_direct_replay_state_and_event_age():
    data = histories()
    context = context_as_of(data, "TEST", "M15", END, stability_window=20)
    closed = filter_closed_bars(data["M15"], "M15", END)
    daily = filter_closed_bars(data["D1"], "D1", END)
    anchors = broker_session_anchors(daily, closed.time.iloc[-1])
    replay = replay_cloudgazer(closed, "TEST", "M15", daily_opens=anchors)
    expected = next(t for t in reversed(replay) if t.new_state != t.previous_state)
    item = context.context_for("M15")
    assert item.cloudgazer_state == replay[-1].new_state
    assert context.cloudgazer_transition == expected
    expected_age = len(closed) - 1 - closed.index[closed.time == expected.bar_open_time][-1]
    assert context.event_age_bars == expected_age
    assert item.state_event_age_bars == expected_age


def test_stability_counts_state_changes_in_exact_closed_bar_window():
    data = histories()
    context = context_as_of(data, "TEST", "M15", END, stability_window=20)
    item = context.context_for("M15")
    closed = filter_closed_bars(data["M15"], "M15", END)
    anchors = broker_session_anchors(filter_closed_bars(data["D1"], "D1", END), closed.time.iloc[-1])
    replay = replay_cloudgazer(closed, "TEST", "M15", daily_opens=anchors)
    recent = set(pd.to_datetime(closed.time.iloc[-20:], utc=True))
    expected = sum(t.new_state != t.previous_state and pd.Timestamp(t.bar_open_time) in recent for t in replay)
    assert (item.recent_state_changes, item.observed_bars) == (expected, 20)


def test_historical_context_excludes_h1_and_h4_bars_closing_after_event():
    data = histories()
    event_cutoff = END - timedelta(minutes=15)
    context = context_as_of(data, "TEST", "M15", event_cutoff)
    h1 = context.context_for("H1")
    h4 = context.context_for("H4")
    assert h1.market_candle_time + bar_duration("H1") <= event_cutoff
    assert h4.market_candle_time + bar_duration("H4") <= event_cutoff
    assert h1.market_candle_time == END - timedelta(hours=2)
    assert h4.market_candle_time == END - timedelta(hours=8)


def test_context_for_event_uses_event_candle_close_as_causal_cutoff():
    data = histories()
    all_context = context_as_of(data, "TEST", "M15", END)
    transition = all_context.cloudgazer_transition
    historical = context_for_event(data, "TEST", "M15", transition)
    assert historical.evaluated_at == transition.bar_open_time + timedelta(minutes=15)
    for item in historical.timeframe_contexts:
        if item.market_candle_time is not None:
            assert item.market_candle_time + bar_duration(item.timeframe) <= historical.evaluated_at


def test_generation_is_deterministic():
    data = histories()
    assert context_as_of(data, "TEST", "M15", END) == context_as_of(data, "TEST", "M15", END)


def test_missing_higher_timeframe_is_explicitly_unavailable():
    data = {"M15": history("M15"), "D1": history("D1")}
    context = context_as_of(data, "TEST", "M15", END)
    missing = context.context_for("H1")
    assert missing.market_direction is None
    assert missing.cloudgazer_state is None
    assert missing.structural_alignment == Alignment.UNAVAILABLE
    assert missing.observed_bars == 0
