"""Pure Phase 1.8B context construction over validated candle histories."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..analysis.market_state import MarketStateAnalyzer
from ..mt5.closure import bar_duration, filter_closed_bars
from ..signals.cloudgazer import replay_cloudgazer
from ..signals.models import CloudgazerState, CloudgazerTransition
from ..signals.vwap_events import broker_session_anchors
from .alignment import cloudgazer_alignment, direction_for_event, structural_alignment
from .models import Alignment, SignalContext, TimeframeContext, TimeframeRole

SUPPORTED_CONTEXT_TIMEFRAMES = ("M15", "H1", "H4", "D1")


def timeframe_role(timeframe: str, event_timeframe: str) -> TimeframeRole:
    if timeframe == event_timeframe:
        return TimeframeRole.EVENT
    return {
        "H1": TimeframeRole.INTERMEDIATE,
        "H4": TimeframeRole.PRIMARY_HIGHER,
        "D1": TimeframeRole.MACRO,
    }.get(timeframe, TimeframeRole.INTERMEDIATE)


def relevant_timeframes(event_timeframe: str) -> tuple[str, ...]:
    if event_timeframe not in SUPPORTED_CONTEXT_TIMEFRAMES:
        raise ValueError(f"Unsupported event timeframe: {event_timeframe}")
    start = SUPPORTED_CONTEXT_TIMEFRAMES.index(event_timeframe)
    return SUPPORTED_CONTEXT_TIMEFRAMES[start:]


def context_as_of(
    histories: dict[str, pd.DataFrame],
    symbol: str,
    event_timeframe: str,
    as_of: datetime,
    *,
    stability_window: int = 20,
) -> SignalContext:
    """Describe the latest event and structure known at ``as_of``.

    Every dataset is filtered through the shared closure implementation, so a
    bar is eligible only when ``bar_open + timeframe_duration <= as_of``.
    """
    return _build_context(histories, symbol, event_timeframe, as_of, stability_window, None)


def context_for_event(
    histories: dict[str, pd.DataFrame],
    symbol: str,
    event_timeframe: str,
    transition: CloudgazerTransition,
    *,
    stability_window: int = 20,
) -> SignalContext:
    """Return facts available when a historical event candle closed."""
    evaluated_at = transition.bar_open_time + bar_duration(event_timeframe)
    return _build_context(
        histories, symbol, event_timeframe, evaluated_at, stability_window, transition
    )


def _build_context(
    histories: dict[str, pd.DataFrame],
    symbol: str,
    event_timeframe: str,
    as_of: datetime,
    stability_window: int,
    requested_transition: CloudgazerTransition | None,
) -> SignalContext:
    if stability_window < 1:
        raise ValueError("stability_window must be positive")
    if event_timeframe not in SUPPORTED_CONTEXT_TIMEFRAMES:
        raise ValueError(f"Unsupported event timeframe: {event_timeframe}")
    as_of = _as_utc(as_of)
    closed = {
        tf: _closed_as_of(histories.get(tf), tf, as_of)
        for tf in relevant_timeframes(event_timeframe)
    }
    daily = _closed_as_of(histories.get("D1"), "D1", as_of)
    replays = {
        tf: _replay(closed[tf], daily, symbol, tf)
        for tf in relevant_timeframes(event_timeframe)
    }

    event_replay = replays[event_timeframe]
    latest_transition = requested_transition or _latest_state_change(event_replay)
    # A supplied transition must itself have been available at this cutoff.
    if requested_transition is not None and (
        requested_transition.bar_open_time + bar_duration(event_timeframe) > as_of
    ):
        raise ValueError("event candle was not closed at evaluated_at")
    event = latest_transition.winning_event.event_type if latest_transition and latest_transition.winning_event else None
    direction = direction_for_event(event)
    event_bars = closed[event_timeframe]
    event_age = _bars_ago(event_bars, latest_transition.bar_open_time) if latest_transition else None

    analyzer = MarketStateAnalyzer()
    contexts = []
    for tf in relevant_timeframes(event_timeframe):
        bars = closed[tf]
        replay = replays[tf]
        state = replay[-1].new_state if replay else (CloudgazerState.FLAT if not bars.empty else None)
        state_event = _latest_state_change(replay)
        market = analyzer.analyze(bars, symbol, tf) if not bars.empty else None
        market_available = market is not None and market.candle_time is not None
        market_direction = market.direction if market_available else None
        market_condition = market.condition if market_available else None
        changes, observed = _stability(bars, replay, stability_window)
        contexts.append(TimeframeContext(
            timeframe=tf,
            role=timeframe_role(tf, event_timeframe),
            market_direction=market_direction,
            market_condition=market_condition,
            market_candle_time=market.candle_time if market_available else None,
            cloudgazer_state=state,
            structural_alignment=structural_alignment(direction, market_direction),
            cloudgazer_alignment=cloudgazer_alignment(direction, state),
            latest_state_event=(state_event.winning_event.event_type
                                if state_event and state_event.winning_event else None),
            latest_state_event_time=state_event.bar_open_time if state_event else None,
            state_event_age_bars=(_bars_ago(bars, state_event.bar_open_time)
                                  if state_event else None),
            recent_state_changes=changes,
            observed_bars=observed,
        ))

    event_state = (latest_transition.new_state if latest_transition else
                   (event_replay[-1].new_state if event_replay else None))
    return SignalContext(
        symbol=symbol,
        event_timeframe=event_timeframe,
        evaluated_at=as_of,
        event_direction=direction,
        latest_event=event,
        cloudgazer_transition=latest_transition,
        cloudgazer_state=event_state,
        event_age_bars=event_age,
        stability_window=stability_window,
        timeframe_contexts=tuple(contexts),
    )


def _closed_as_of(df: pd.DataFrame | None, timeframe: str, as_of: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    return filter_closed_bars(df, timeframe, as_of).sort_values("time").reset_index(drop=True)


def _replay(bars: pd.DataFrame, daily: pd.DataFrame, symbol: str, timeframe: str):
    if bars.empty:
        return ()
    anchors = broker_session_anchors(daily, pd.Timestamp(bars["time"].iloc[-1]))
    # Historical fixtures may omit D1 data; explicit UNAVAILABLE structure is
    # still preferable to fabricating it, while same-timeframe replay remains
    # deterministic via the documented UTC fallback.
    return replay_cloudgazer(
        bars, symbol, timeframe, daily_opens=None if anchors.empty else anchors
    )


def _latest_state_change(replay) -> CloudgazerTransition | None:
    return next((item for item in reversed(replay) if item.new_state != item.previous_state), None)


def _bars_ago(bars: pd.DataFrame, event_time: datetime) -> int | None:
    if bars.empty:
        return None
    times = pd.to_datetime(bars["time"], utc=True)
    matches = times == pd.Timestamp(event_time)
    if not matches.any():
        return None
    position = int(matches[matches].index[-1])
    # Frames are reset-indexed by _closed_as_of.
    return len(bars) - 1 - position


def _stability(bars: pd.DataFrame, replay, window: int) -> tuple[int, int]:
    observed = min(len(bars), window)
    if observed == 0:
        return 0, 0
    recent_times = set(pd.to_datetime(bars["time"].iloc[-observed:], utc=True).tolist())
    changes = sum(
        item.new_state != item.previous_state and pd.Timestamp(item.bar_open_time) in recent_times
        for item in replay
    )
    return int(changes), observed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
