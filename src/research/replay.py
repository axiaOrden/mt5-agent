"""Offline deterministic orchestration of existing signal intelligence."""
from __future__ import annotations

import pandas as pd
from datetime import datetime

from ..context.engine import context_for_event
from ..mt5.closure import bar_duration
from ..signals.cloudgazer import replay_cloudgazer
from ..signals.vwap_events import broker_session_anchors
from .models import EventCandle, ReplayEvent, ReplayResult
from .outcomes import measure_forward_outcomes

DEFAULT_HORIZONS = (1, 4, 8, 16, 32)


def replay_history(
    histories: dict[str, pd.DataFrame],
    symbol: str,
    event_timeframe: str = "M15",
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    stability_window: int = 20,
    report_from: datetime | None = None,
    report_to: datetime | None = None,
) -> ReplayResult:
    """Replay state-changing events with causal snapshots and future outcomes.

    This function performs no provider calls and reads no wall clock. Histories
    are treated as already validated closed-bar datasets.
    """
    horizons = _validate_horizons(horizons)
    event_bars = _normalize(histories.get(event_timeframe))
    daily = _normalize(histories.get("D1"))
    if event_bars.empty:
        return ReplayResult(symbol, event_timeframe, horizons, 0, None, None, (), None, True)

    d1_start = pd.Timestamp(daily["time"].iloc[0]).to_pydatetime() if not daily.empty else None
    missing_d1 = daily.empty or pd.Timestamp(daily["time"].iloc[0]) > pd.Timestamp(event_bars["time"].iloc[0])
    if daily.empty:
        # VWAP participates in state reduction. UTC fallback would silently
        # invent transitions, so exact replay is unavailable without D1 opens.
        return ReplayResult(
            symbol, event_timeframe, horizons, len(event_bars),
            pd.Timestamp(event_bars["time"].iloc[0]).to_pydatetime(),
            pd.Timestamp(event_bars["time"].iloc[-1]).to_pydatetime(),
            (), None, True,
        )

    anchors = broker_session_anchors(daily, pd.Timestamp(event_bars["time"].iloc[-1]))
    transitions = replay_cloudgazer(
        event_bars, symbol, event_timeframe, daily_opens=anchors
    )
    positions = {pd.Timestamp(value): index for index, value in enumerate(event_bars["time"])}
    records = []
    for transition in transitions:
        if transition.new_state == transition.previous_state or transition.winning_event is None:
            continue
        knowledge_time = transition.bar_open_time + bar_duration(event_timeframe)
        if (report_from is not None and knowledge_time < report_from) or (report_to is not None and knowledge_time >= report_to):
            continue
        event_time = pd.Timestamp(transition.bar_open_time)
        index = positions[event_time]
        context = context_for_event(
            histories, symbol, event_timeframe, transition,
            stability_window=stability_window,
        )
        if context.event_direction is None:
            continue
        row = event_bars.iloc[index]
        candle = EventCandle(
            open=float(row["open"]), high=float(row["high"]), low=float(row["low"]),
            close=float(row["close"]), tick_volume=_optional_float(row, "tick_volume"),
            real_volume=_optional_float(row, "real_volume"),
        )
        records.append(ReplayEvent(
            symbol=symbol,
            event_timeframe=event_timeframe,
            event_bar_open_time=transition.bar_open_time,
            event_knowledge_time=knowledge_time,
            event_type=transition.winning_event.event_type,
            event_direction=context.event_direction,
            previous_state=transition.previous_state,
            new_state=transition.new_state,
            label=transition.label,
            event_candle=candle,
            event_pvsra=context.event_pvsra,
            timeframe_contexts=context.timeframe_contexts,
            outcomes=measure_forward_outcomes(
                event_bars, index, candle.close, context.event_direction, horizons
            ),
        ))
    return ReplayResult(
        symbol=symbol,
        event_timeframe=event_timeframe,
        horizons=horizons,
        closed_candles=len(event_bars),
        period_start=pd.Timestamp(event_bars["time"].iloc[0]).to_pydatetime(),
        period_end=pd.Timestamp(event_bars["time"].iloc[-1]).to_pydatetime(),
        events=tuple(records),
        d1_coverage_start=d1_start,
        missing_d1_coverage=missing_d1,
    )


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True).copy()
    result["time"] = pd.to_datetime(result["time"], utc=True)
    return result


def _validate_horizons(horizons) -> tuple[int, ...]:
    values = tuple(sorted(set(int(value) for value in horizons)))
    if not values or any(value < 1 for value in values):
        raise ValueError("at least one positive horizon is required")
    return values


def _optional_float(row: pd.Series, name: str) -> float | None:
    if name not in row or pd.isna(row[name]):
        return None
    return float(row[name])
