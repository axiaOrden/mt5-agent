from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.context.models import Direction
from src.mt5.closure import bar_duration
from src.research import (
    export_parquet, measure_forward_outcomes, replay_frame, replay_history, summarize,
)
from src.signals.cloudgazer import replay_cloudgazer
from src.signals.vwap_events import broker_session_anchors


END = datetime(2026, 4, 10, 12, tzinfo=timezone.utc)
DELTAS = {"M15": timedelta(minutes=15), "H1": timedelta(hours=1),
          "H4": timedelta(hours=4), "D1": timedelta(days=1)}


def history(timeframe, n=140):
    delta = DELTAS[timeframe]
    x = np.arange(n)
    close = 100 + np.sin(x / 2.1) * 7 + x * .02
    open_ = close + np.cos(x / 1.8)
    return pd.DataFrame({
        "time": pd.to_datetime([END-delta*(n-i) for i in range(n)], utc=True),
        "open": open_, "high": np.maximum(open_, close)+2,
        "low": np.minimum(open_, close)-2, "close": close,
        "tick_volume": 10+x%9, "spread": 1, "real_volume": 0,
    })


def histories():
    return {tf: history(tf) for tf in DELTAS}


def test_event_sequence_transitions_labels_and_knowledge_time():
    data = histories()
    result = replay_history(data, "TEST", horizons=(1, 4))
    anchors = broker_session_anchors(data["D1"], data["M15"].time.iloc[-1])
    direct = replay_cloudgazer(data["M15"], "TEST", "M15", daily_opens=anchors)
    expected = [item for item in direct if item.new_state != item.previous_state]
    assert [event.event_type for event in result.events] == [item.winning_event.event_type for item in expected]
    assert [(event.previous_state, event.new_state, event.label) for event in result.events] == [
        (item.previous_state, item.new_state, item.label) for item in expected
    ]
    assert all(event.event_knowledge_time == event.event_bar_open_time + timedelta(minutes=15)
               for event in result.events)


def test_historical_snapshot_has_only_causally_closed_higher_bars():
    result = replay_history(histories(), "TEST", horizons=(1,))
    for event in result.events:
        for context in event.timeframe_contexts:
            if context.market_candle_time is not None:
                assert context.market_candle_time + bar_duration(context.timeframe) <= event.event_knowledge_time


def test_future_append_cannot_change_existing_snapshot():
    data = histories()
    before = replay_history(data, "TEST", horizons=(1, 8))
    target = before.events[-2]
    expanded = {key: frame.copy() for key, frame in data.items()}
    future = expanded["M15"].iloc[-1].copy()
    future["time"] = pd.Timestamp(END)
    future[["open", "high", "low", "close"]] = [1000, 2000, 1, 1500]
    future["tick_volume"] = 999999
    expanded["M15"] = pd.concat([expanded["M15"], future.to_frame().T], ignore_index=True)
    after = replay_history(expanded, "TEST", horizons=(1, 8))
    same = next(item for item in after.events if item.event_bar_open_time == target.event_bar_open_time)
    assert replace(target, outcomes=()) == replace(same, outcomes=())


def _outcome_bars():
    return pd.DataFrame({
        "open":[100,100,101,99], "high":[500,105,103,102],
        "low":[1,98,95,97], "close":[100,102,96,101],
    })


def test_bullish_outcome_excludes_event_bar_and_uses_exact_n_bars():
    outcomes = measure_forward_outcomes(_outcome_bars(), 0, 100, Direction.BULLISH, (1, 2))
    assert outcomes[0].future_close == 102
    assert outcomes[0].directional_return == pytest.approx(.02)
    assert outcomes[0].mfe == pytest.approx(.05)
    assert outcomes[0].mae == pytest.approx(.02)
    assert outcomes[1].future_close == 96
    assert outcomes[1].mfe == pytest.approx(.05)
    assert outcomes[1].mae == pytest.approx(.05)


def test_bearish_directional_return_mfe_and_mae():
    outcome = measure_forward_outcomes(_outcome_bars(), 0, 100, Direction.BEARISH, (2,))[0]
    assert outcome.raw_return == pytest.approx(-.04)
    assert outcome.directional_return == pytest.approx(.04)
    assert outcome.mfe == pytest.approx(.05)
    assert outcome.mae == pytest.approx(.05)


def test_incomplete_horizon_is_explicitly_unavailable():
    outcome = measure_forward_outcomes(_outcome_bars(), 2, 96, Direction.BULLISH, (2,))[0]
    assert not outcome.available
    assert outcome.future_close is outcome.raw_return is outcome.mfe is outcome.mae is None


def test_replay_is_deterministic_and_wall_clock_independent():
    data = histories()
    assert replay_history(data, "TEST") == replay_history(data, "TEST")


def test_missing_higher_timeframe_is_explicit_context_unavailable():
    data = {"M15": history("M15"), "D1": history("D1")}
    result = replay_history(data, "TEST", horizons=(1,))
    h1 = result.events[0].context_for("H1")
    assert h1.market_direction is None and h1.cloudgazer_state is None


def test_missing_d1_prevents_silent_utc_replay():
    result = replay_history({"M15": history("M15")}, "TEST")
    assert result.missing_d1_coverage
    assert result.events == ()


def test_statistics_counts_and_excludes_unavailable_horizons():
    result = replay_history(histories(), "TEST", horizons=(1, 32))
    overall = summarize(result.events, result.horizons)[0]
    h1 = overall.horizons[0]
    h32 = overall.horizons[1]
    expected1 = [event.outcomes[0].directional_return for event in result.events
                 if event.outcomes[0].available]
    assert h1.sample_count == len(expected1)
    assert h1.mean_directional_return == pytest.approx(float(np.mean(expected1)))
    assert h1.median_directional_return == pytest.approx(float(np.median(expected1)))
    assert h32.sample_count < len(result.events)


def test_grouped_statistics_event_type_and_alignment():
    result = replay_history(histories(), "TEST", horizons=(1,))
    by_type = summarize(result.events, result.horizons, group_by="event_type")
    assert sum(group.event_count for group in by_type) == len(result.events)
    by_h1 = summarize(result.events, result.horizons, group_by="H1_structural_alignment")
    assert sum(group.event_count for group in by_h1) == len(result.events)


def test_parquet_round_trip_preserves_timestamps_and_primitives(tmp_path):
    result = replay_history(histories(), "TEST", horizons=(1, 4))
    path = export_parquet(result, tmp_path / "events.parquet")
    loaded = pd.read_parquet(path)
    expected = replay_frame(result)
    pd.testing.assert_frame_equal(loaded, expected)
    assert str(loaded.event_bar_open_time.dtype).endswith("UTC]")
    assert set(loaded.event_type).issubset({
        "VWAP_CROSS_BULLISH", "VWAP_CROSS_BEARISH", "TK_CROSS_BULLISH", "TK_CROSS_BEARISH"
    })
