"""Indexed, causal Phase 1.9 context snapshots over immutable histories.

The live context API remains the reference implementation. Research reuses one
Cloudgazer stream per timeframe and looks up the prefix known at each event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..analysis.market_state import MarketStateAnalyzer
from ..context.alignment import cloudgazer_alignment, direction_for_event, structural_alignment
from ..context.engine import context_for_event, relevant_timeframes, timeframe_role
from ..context.models import SignalContext, TimeframeContext
from ..mt5.closure import bar_duration
from ..signals.cloudgazer import replay_cloudgazer
from ..signals.models import CloudgazerState, CloudgazerTransition
from ..signals.vwap_events import broker_session_anchors
from .pvsra_index import PVSRAIndex


@dataclass
class _Timeline:
    bars: pd.DataFrame
    timeframe: str
    transitions: tuple[CloudgazerTransition, ...]
    times_ns: np.ndarray
    change_positions: np.ndarray
    market_cache: dict[int, object] = field(default_factory=dict)

    @classmethod
    def build(cls, bars: pd.DataFrame, timeframe: str, symbol: str,
              daily: pd.DataFrame) -> "_Timeline":
        if bars is None or bars.empty:
            empty = pd.DataFrame()
            return cls(empty, timeframe, (), np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64))
        frame = bars.sort_values("time").reset_index(drop=True)
        anchors = broker_session_anchors(daily, pd.Timestamp(frame["time"].iloc[-1]))
        transitions = replay_cloudgazer(
            frame, symbol, timeframe, daily_opens=None if anchors.empty else anchors
        )
        times = pd.to_datetime(frame["time"], utc=True).astype("datetime64[ns, UTC]").astype("int64").to_numpy()
        changes = np.fromiter(
            (i + 1 for i, transition in enumerate(transitions)
             if transition.new_state != transition.previous_state),
            dtype=np.int64,
        )
        return cls(frame, timeframe, transitions, times, changes)

    def count_as_of(self, as_of: datetime) -> int:
        cutoff = pd.Timestamp(as_of).value - pd.Timedelta(bar_duration(self.timeframe)).value
        return int(np.searchsorted(self.times_ns, cutoff, side="right"))

    def latest_change(self, count: int) -> tuple[CloudgazerTransition | None, int | None]:
        index = int(np.searchsorted(self.change_positions, count, side="left")) - 1
        if index < 0:
            return None, None
        position = int(self.change_positions[index])
        return self.transitions[position - 1], position

    def stability(self, count: int, window: int) -> tuple[int, int]:
        observed = min(count, window)
        if observed == 0:
            return 0, 0
        before = int(np.searchsorted(self.change_positions, count - observed, side="left"))
        through = int(np.searchsorted(self.change_positions, count, side="left"))
        return through - before, observed

    def market(self, count: int, symbol: str):
        if count == 0:
            return None
        if count not in self.market_cache:
            # Context exposes direction, condition and candle time. Their
            # longest Ichimoku dependency is Senkou B (52), displaced 26,
            # then inspected 26 bars back for Chikou: 104 bars total. ATR's
            # full-history thickness diagnostic is not part of SignalContext.
            # Preserve the first 104-bar warmup exactly.
            market_bars = self.bars.iloc[max(0, count - 104):count].reset_index(drop=True)
            self.market_cache[count] = MarketStateAnalyzer().analyze(
                market_bars, symbol, self.timeframe
            )
        return self.market_cache[count]

    def position(self, bar_open_time: datetime, count: int) -> int | None:
        index = int(np.searchsorted(self.times_ns, pd.Timestamp(bar_open_time).value))
        if index >= count or index >= len(self.times_ns) or self.times_ns[index] != pd.Timestamp(bar_open_time).value:
            return None
        return index


class ResearchContextIndex:
    """One Cloudgazer timeline per relevant timeframe, with as-of lookups."""

    def __init__(self, histories: dict[str, pd.DataFrame], symbol: str,
                 event_timeframe: str, event_bars: pd.DataFrame,
                 daily: pd.DataFrame, stability_window: int):
        if stability_window < 1:
            raise ValueError("stability_window must be positive")
        self.histories = histories
        self.symbol = symbol
        self.event_timeframe = event_timeframe
        self.stability_window = stability_window
        self.timeframes = relevant_timeframes(event_timeframe)
        self.timelines = {
            tf: _Timeline.build(
                event_bars if tf == event_timeframe else
                (daily if tf == "D1" else histories.get(tf)),
                tf, symbol, daily,
            ) for tf in self.timeframes
        }
        self.daily = _Timeline.build(daily, "D1", symbol, daily) if "D1" not in self.timelines else self.timelines["D1"]
        self.daily_opens_ns = self.daily.times_ns
        event_frame = self.timelines[event_timeframe].bars
        pvsra_anchors = broker_session_anchors(daily, pd.Timestamp(event_frame["time"].iloc[-1]))
        self.pvsra = PVSRAIndex(event_frame, pvsra_anchors)

    @property
    def event_transitions(self) -> tuple[CloudgazerTransition, ...]:
        return self.timelines[self.event_timeframe].transitions

    def _requires_legacy_anchor(self, as_of: datetime) -> bool:
        """Honor legacy prefix replay when an unclosed D1 anchor differs.

        A broker session-clock shift can make the actual current D1 open differ
        from the prior closed D1 open plus 24-hour cadence. The live context
        path deliberately cannot know that open until D1 closes.
        """
        daily_count = self.daily.count_as_of(as_of)
        if daily_count == 0:
            return True
        event_timeline = self.timelines[self.event_timeframe]
        event_count = event_timeline.count_as_of(as_of)
        if event_count == 0:
            return False
        last_bar_ns = int(event_timeline.times_ns[event_count - 1])
        actual_index = int(np.searchsorted(self.daily_opens_ns, last_bar_ns, side="right")) - 1
        if actual_index < 0:
            return True
        prior = int(self.daily_opens_ns[daily_count - 1])
        day_ns = pd.Timedelta(days=1).value
        predicted = prior + max(0, (last_bar_ns - prior) // day_ns) * day_ns
        return int(self.daily_opens_ns[actual_index]) != predicted

    def context_for_event(self, transition: CloudgazerTransition) -> SignalContext:
        as_of = transition.bar_open_time + bar_duration(self.event_timeframe)
        if self._requires_legacy_anchor(as_of):
            return context_for_event(
                self.histories, self.symbol, self.event_timeframe, transition,
                stability_window=self.stability_window,
            )
        event_type = transition.winning_event.event_type if transition.winning_event else None
        direction = direction_for_event(event_type)
        event_timeline = self.timelines[self.event_timeframe]
        event_count = event_timeline.count_as_of(as_of)
        event_position = event_timeline.position(transition.bar_open_time, event_count)
        event_age = event_count - 1 - event_position if event_position is not None else None
        event_pvsra = self.pvsra.at(event_position) if event_position is not None else None

        contexts = []
        for timeframe in self.timeframes:
            timeline = self.timelines[timeframe]
            count = timeline.count_as_of(as_of)
            state = (timeline.transitions[count - 2].new_state if count >= 2 else
                     (CloudgazerState.FLAT if count else None))
            state_event, state_position = timeline.latest_change(count)
            market = timeline.market(count, self.symbol)
            market_available = market is not None and market.candle_time is not None
            market_direction = market.direction if market_available else None
            market_condition = market.condition if market_available else None
            changes, observed = timeline.stability(count, self.stability_window)
            contexts.append(TimeframeContext(
                timeframe=timeframe,
                role=timeframe_role(timeframe, self.event_timeframe),
                market_direction=market_direction,
                market_condition=market_condition,
                market_candle_time=market.candle_time if market_available else None,
                cloudgazer_state=state,
                structural_alignment=structural_alignment(direction, market_direction),
                cloudgazer_alignment=cloudgazer_alignment(direction, state),
                latest_state_event=(state_event.winning_event.event_type
                                    if state_event and state_event.winning_event else None),
                latest_state_event_time=state_event.bar_open_time if state_event else None,
                state_event_age_bars=count - 1 - state_position if state_position is not None else None,
                recent_state_changes=changes,
                observed_bars=observed,
            ))
        return SignalContext(
            symbol=self.symbol,
            event_timeframe=self.event_timeframe,
            evaluated_at=as_of,
            event_direction=direction,
            latest_event=event_type,
            cloudgazer_transition=transition,
            cloudgazer_state=transition.new_state,
            event_age_bars=event_age,
            event_pvsra=event_pvsra,
            stability_window=self.stability_window,
            timeframe_contexts=tuple(contexts),
        )
