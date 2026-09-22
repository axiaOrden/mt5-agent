"""Pure Cloudgazer reducer and deterministic historical replay."""
from __future__ import annotations

import pandas as pd
from .models import CloudgazerState, CloudgazerTransition, EventType, SignalEvent
from .ichimoku_events import cloudgazer_ichimoku, tk_cross
from .vwap_events import session_vwap, vwap_cross
from .candle_events import engulfing
from ..mt5.closure import filter_closed_bars

_PRIORITY = (EventType.VWAP_CROSS_BULLISH, EventType.VWAP_CROSS_BEARISH,
             EventType.TK_CROSS_BULLISH, EventType.TK_CROSS_BEARISH)


def reduce_cloudgazer(previous_state: CloudgazerState, raw_events: tuple[SignalEvent, ...],
                      close: float, span_a: float, span_b: float,
                      bar_open_time=None) -> CloudgazerTransition:
    if raw_events:
        identities = {e.identity for e in raw_events}
        if len(identities) != len(raw_events):
            raise ValueError("duplicate signal events")
        times = {e.bar_open_time for e in raw_events}
        if len(times) != 1 or (bar_open_time is not None and bar_open_time not in times):
            raise ValueError("events must belong to one candle")
        bar_open_time = next(iter(times))
    if bar_open_time is None:
        raise ValueError("bar_open_time required when there are no events")
    winner = next((e for kind in _PRIORITY for e in raw_events if e.event_type == kind), None)
    suppressed = tuple(e for e in raw_events if e is not winner and e.event_type in _PRIORITY)
    state, label = previous_state, None
    if winner:
        kind = winner.event_type
        if kind in (EventType.VWAP_CROSS_BULLISH, EventType.TK_CROSS_BULLISH):
            if previous_state != CloudgazerState.LONG:
                state = CloudgazerState.LONG
                label = "BUY" if kind == EventType.VWAP_CROSS_BULLISH or previous_state == CloudgazerState.SHORT or (close > span_a and close > span_b) else "WB"
        else:
            if previous_state != CloudgazerState.SHORT:
                state = CloudgazerState.SHORT
                label = "SELL" if kind == EventType.VWAP_CROSS_BEARISH or previous_state == CloudgazerState.LONG or (close < span_a and close < span_b) else "WS"
    return CloudgazerTransition(bar_open_time, raw_events, winner, suppressed, previous_state, state, label)


def replay_cloudgazer(df: pd.DataFrame, symbol: str, timeframe: str,
                       *, broker_now=None, daily_opens: pd.Series | None = None) -> tuple[CloudgazerTransition, ...]:
    """Replay chronological closed candles. Live calls require broker tick time.

    Without broker_now, caller explicitly supplies an already validated closed
    historical dataset. A live caller must pass broker_now; closure.py filters it.
    """
    if df is None or df.empty:
        return ()
    bars = filter_closed_bars(df, timeframe, broker_now) if broker_now is not None else df.copy()
    bars = bars.sort_values("time").reset_index(drop=True)
    if bars["time"].duplicated().any():
        raise ValueError("duplicate candle timestamps")
    ichi = cloudgazer_ichimoku(bars)
    vwap = session_vwap(bars, daily_opens)
    state = CloudgazerState.FLAT
    transitions = []
    for i in range(1, len(bars)):
        bar = bars.iloc[i]
        prev = bars.iloc[i - 1]
        time = pd.Timestamp(bar["time"]).to_pydatetime()
        kinds = (vwap_cross(prev["close"], vwap.iloc[i - 1], bar["close"], vwap.iloc[i]),
                 tk_cross(ichi.tenkan.iloc[i - 1], ichi.kijun.iloc[i - 1], ichi.tenkan.iloc[i], ichi.kijun.iloc[i]),
                 engulfing(prev["open"], prev["close"], bar["open"], bar["close"]))
        events = tuple(SignalEvent(symbol, timeframe, time, kind) for kind in kinds if kind is not None)
        transition = reduce_cloudgazer(state, events, float(bar["close"]),
                                        float(ichi.span_a.iloc[i]), float(ichi.span_b.iloc[i]), time)
        transitions.append(transition)
        state = transition.new_state
    return tuple(transitions)
