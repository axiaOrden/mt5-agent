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
from src.research.context_index import ResearchContextIndex
from src.research.pvsra_index import PVSRAIndex
from src.context.engine import context_for_event as legacy_context_for_event
from src.context.engine import relevant_timeframes
from src.analysis.market_state import MarketStateAnalyzer
from src.signals.cloudgazer import reduce_cloudgazer, replay_cloudgazer
from src.signals.ichimoku_events import cloudgazer_ichimoku, tk_cross
from src.signals.vwap_events import broker_session_anchors, session_vwap, vwap_cross
from src.signals.candle_events import engulfing
from src.signals.models import CloudgazerState, SignalEvent
from src.pvsra.engine import analyze_pvsra


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


def test_research_filter_preserves_warmup_state_and_event_snapshots():
    data = histories()
    full = replay_history(data, "TEST", horizons=(1,))
    assert len(full.events) > 2
    cutoff = full.events[len(full.events) // 2].event_knowledge_time
    filtered = replay_history(data, "TEST", horizons=(1,), report_from=cutoff)
    assert filtered.events == tuple(event for event in full.events if event.event_knowledge_time >= cutoff)
    assert filtered.events[0].previous_state == full.events[len(full.events) // 2].previous_state
    assert filtered.events[0].previous_state.value == "LONG"
    assert filtered.events[0].new_state.value == "SHORT"


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


@pytest.mark.parametrize("event_timeframe", ("M15", "H1", "H4", "D1"))
def test_indexed_research_matches_legacy_context_and_export(monkeypatch, event_timeframe):
    data = histories()
    optimized = replay_history(data, "TEST", event_timeframe, horizons=(1, 4, 8))

    def legacy(self, transition):
        return legacy_context_for_event(
            self.histories, self.symbol, self.event_timeframe, transition,
            stability_window=self.stability_window,
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(ResearchContextIndex, "context_for_event", legacy)
        baseline = replay_history(data, "TEST", event_timeframe, horizons=(1, 4, 8))

    assert optimized == baseline
    pd.testing.assert_frame_equal(replay_frame(optimized), replay_frame(baseline))
    assert summarize(optimized.events, optimized.horizons) == summarize(baseline.events, baseline.horizons)
    assert summarize(optimized.events, optimized.horizons, group_by="pvsra_classification") == summarize(
        baseline.events, baseline.horizons, group_by="pvsra_classification")


def test_research_cloudgazer_calls_scale_with_timeframes(monkeypatch):
    import src.research.context_index as indexed_module
    import src.context.engine as context_module
    real = indexed_module.replay_cloudgazer
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[2])
        return real(*args, **kwargs)

    monkeypatch.setattr(indexed_module, "replay_cloudgazer", counted)
    monkeypatch.setattr(context_module, "replay_cloudgazer", counted)
    data = histories()
    result = replay_history(data, "TEST", horizons=(1,))
    assert len(result.events) > 4
    assert calls == list(relevant_timeframes("M15"))
    index = ResearchContextIndex(data, "TEST", "M15", data["M15"], data["D1"], 20)
    anchors = broker_session_anchors(data["D1"], data["M15"].time.iloc[-1])
    assert index.event_transitions == replay_cloudgazer(data["M15"], "TEST", "M15", daily_opens=anchors)


def test_session_clock_shift_uses_exact_legacy_prefix_context(monkeypatch):
    import src.research.context_index as indexed_module
    data = histories()
    daily = data["D1"].copy()
    shifted = daily["time"] >= pd.Timestamp("2026-04-09 12:00", tz="UTC")
    daily.loc[shifted, "time"] += pd.Timedelta(hours=1)
    data["D1"] = daily
    fallback_calls = []
    real = indexed_module.context_for_event

    def counted(*args, **kwargs):
        fallback_calls.append(args[3].bar_open_time)
        return real(*args, **kwargs)

    monkeypatch.setattr(indexed_module, "context_for_event", counted)
    optimized = replay_history(data, "TEST", horizons=(1,))
    assert fallback_calls

    def legacy(self, transition):
        return real(self.histories, self.symbol, self.event_timeframe, transition,
                    stability_window=self.stability_window)

    monkeypatch.setattr(ResearchContextIndex, "context_for_event", legacy)
    baseline = replay_history(data, "TEST", horizons=(1,))
    assert optimized == baseline


def test_numpy_cloudgazer_loop_matches_scalar_reference_including_suppression():
    data = histories()
    bars = data["M15"].sort_values("time").reset_index(drop=True)
    anchors = broker_session_anchors(data["D1"], bars.time.iloc[-1])
    ichi = cloudgazer_ichimoku(bars)
    vwap = session_vwap(bars, anchors)
    state = CloudgazerState.FLAT
    reference = []
    for i in range(1, len(bars)):
        bar, previous = bars.iloc[i], bars.iloc[i - 1]
        time = pd.Timestamp(bar["time"]).to_pydatetime()
        kinds = (
            vwap_cross(previous["close"], vwap.iloc[i - 1], bar["close"], vwap.iloc[i]),
            tk_cross(ichi.tenkan.iloc[i - 1], ichi.kijun.iloc[i - 1],
                     ichi.tenkan.iloc[i], ichi.kijun.iloc[i]),
            engulfing(previous["open"], previous["close"], bar["open"], bar["close"]),
        )
        events = tuple(SignalEvent("TEST", "M15", time, kind) for kind in kinds if kind is not None)
        transition = reduce_cloudgazer(state, events, float(bar["close"]),
                                        float(ichi.span_a.iloc[i]), float(ichi.span_b.iloc[i]), time)
        reference.append(transition)
        state = transition.new_state
    assert replay_cloudgazer(bars, "TEST", "M15", daily_opens=anchors) == tuple(reference)


def test_indexed_pvsra_matches_prefix_engine_across_volume_source_changes():
    times = pd.date_range("2026-01-01", periods=120, freq="15min", tz="UTC")
    values = np.arange(120)
    bars = pd.DataFrame({
        "time": times,
        "open": 100 + values * .01,
        "high": 101 + values * .01,
        "low": 99 + values * .01,
        "close": 100.5 + values * .01,
        "tick_volume": np.full(120, 10.0),
        "real_volume": np.zeros(120),
        "spread": np.ones(120),
    })
    bars.loc[20, "real_volume"] = 5.0
    bars.loc[40, "real_volume"] = np.nan
    bars.loc[50, "tick_volume"] = np.nan
    anchors = pd.Series(pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True))
    index = PVSRAIndex(bars, anchors)
    for position in (0, 19, 20, 39, 40, 50, 95, 96, 110):
        bar_time = times[position]
        expected = analyze_pvsra(
            bars.iloc[:position + 1], "M15", bar_open_time=bar_time,
            daily_opens=anchors[anchors <= bar_time],
        )
        assert index.at(position) == expected


@pytest.mark.parametrize("timeframe", ("M15", "H1", "H4", "D1"))
def test_bounded_market_context_fields_equal_full_prefix(timeframe):
    bars = history(timeframe, n=500)
    analyzer = MarketStateAnalyzer()
    for count in (78, 103, 104, 105, 150, 300, 500):
        full = analyzer.analyze(bars.iloc[:count], "TEST", timeframe)
        bounded = analyzer.analyze(bars.iloc[max(0, count - 104):count].reset_index(drop=True),
                                   "TEST", timeframe)
        assert (bounded.direction, bounded.condition, bounded.candle_time) == (
            full.direction, full.condition, full.candle_time)
