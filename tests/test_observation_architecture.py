"""Conflicting observations remain independent research facts."""
from datetime import datetime, timezone

from src.context.models import Alignment, Direction, TimeframeContext, TimeframeRole
from src.pvsra.models import CandleDirection, PVSRAClassification, PVSRAResult, VolumeSource
from src.research.analysis import cohort_statistics
from src.research.export import replay_frame
from src.research.models import EventCandle, ForwardOutcome, ReplayEvent, ReplayResult
from src.signals.models import CloudgazerState, EventType


def test_conflicting_cloudgazer_pvsra_and_structure_are_preserved():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pvsra = PVSRAResult(
        stamp, PVSRAClassification.CLIMAX, CandleDirection.BULLISH,
        VolumeSource.TICK_VOLUME, 50., 20., 2.5, 10., 5., 2.,
        100., 4., 2., 2.,
    )
    context = TimeframeContext(
        timeframe="H4", role=TimeframeRole.PRIMARY_HIGHER,
        market_direction="BEARISH", market_condition="ESTABLISHED",
        market_candle_time=stamp, cloudgazer_state=CloudgazerState.SHORT,
        structural_alignment=Alignment.OPPOSED,
        cloudgazer_alignment=Alignment.OPPOSED,
        latest_state_event=None, latest_state_event_time=None,
        state_event_age_bars=None, recent_state_changes=0, observed_bars=20,
    )
    event = ReplayEvent(
        symbol="TEST", event_timeframe="M15", event_bar_open_time=stamp,
        event_knowledge_time=stamp, event_type=EventType.VWAP_CROSS_BULLISH,
        event_direction=Direction.BULLISH,
        previous_state=CloudgazerState.FLAT, new_state=CloudgazerState.LONG,
        label="BUY", event_candle=EventCandle(100, 105, 95, 102, 50, 0),
        event_pvsra=pvsra, timeframe_contexts=(context,),
        outcomes=(ForwardOutcome(1, True, 103, .01, .01, .03, .02),),
    )
    result = ReplayResult("TEST", "M15", (1,), 1, stamp, stamp, (event,), stamp, False)
    frame = replay_frame(result)
    row = frame.iloc[0]
    assert row["label"] == "BUY"
    assert row["pvsra_classification"] == "CLIMAX"
    assert row["pvsra_direction"] == "BULLISH"
    assert row["h4_direction"] == "BEARISH"
    assert row["h4_structural_alignment"] == "OPPOSED"
    stats = cohort_statistics(frame, ("label", "pvsra_classification", "h4_direction"), (1,))
    assert len(stats) == 1 and stats.iloc[0]["n"] == 1
