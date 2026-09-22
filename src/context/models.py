"""Immutable Phase 1.8B multi-timeframe context facts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..signals.models import CloudgazerState, CloudgazerTransition, EventType


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class Alignment(str, Enum):
    ALIGNED = "ALIGNED"
    OPPOSED = "OPPOSED"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


class TimeframeRole(str, Enum):
    EVENT = "EVENT"
    INTERMEDIATE = "INTERMEDIATE"
    PRIMARY_HIGHER = "PRIMARY_HIGHER"
    MACRO = "MACRO"


@dataclass(frozen=True)
class TimeframeContext:
    timeframe: str
    role: TimeframeRole
    market_direction: str | None
    market_condition: str | None
    market_candle_time: datetime | None
    cloudgazer_state: CloudgazerState | None
    structural_alignment: Alignment
    cloudgazer_alignment: Alignment
    latest_state_event: EventType | None
    latest_state_event_time: datetime | None
    state_event_age_bars: int | None
    recent_state_changes: int
    observed_bars: int


@dataclass(frozen=True)
class SignalContext:
    symbol: str
    event_timeframe: str
    evaluated_at: datetime
    event_direction: Direction | None
    latest_event: EventType | None
    cloudgazer_transition: CloudgazerTransition | None
    cloudgazer_state: CloudgazerState | None
    event_age_bars: int | None
    stability_window: int
    timeframe_contexts: tuple[TimeframeContext, ...]

    def context_for(self, timeframe: str) -> TimeframeContext | None:
        return next((context for context in self.timeframe_contexts if context.timeframe == timeframe), None)
