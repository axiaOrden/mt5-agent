"""Immutable historical replay and descriptive research models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..context.models import Direction, TimeframeContext
from ..pvsra.models import PVSRAResult
from ..signals.models import CloudgazerState, EventType


@dataclass(frozen=True)
class EventCandle:
    open: float
    high: float
    low: float
    close: float
    tick_volume: float | None
    real_volume: float | None


@dataclass(frozen=True)
class ForwardOutcome:
    horizon: int
    available: bool
    future_close: float | None
    raw_return: float | None
    directional_return: float | None
    mfe: float | None
    mae: float | None


@dataclass(frozen=True)
class ReplayEvent:
    symbol: str
    event_timeframe: str
    event_bar_open_time: datetime
    event_knowledge_time: datetime
    event_type: EventType
    event_direction: Direction
    previous_state: CloudgazerState
    new_state: CloudgazerState
    label: str | None
    event_candle: EventCandle
    event_pvsra: PVSRAResult | None
    timeframe_contexts: tuple[TimeframeContext, ...]
    outcomes: tuple[ForwardOutcome, ...]

    def context_for(self, timeframe: str) -> TimeframeContext | None:
        return next((item for item in self.timeframe_contexts if item.timeframe == timeframe), None)


@dataclass(frozen=True)
class ReplayResult:
    symbol: str
    event_timeframe: str
    horizons: tuple[int, ...]
    closed_candles: int
    period_start: datetime | None
    period_end: datetime | None
    events: tuple[ReplayEvent, ...]
    d1_coverage_start: datetime | None
    missing_d1_coverage: bool


@dataclass(frozen=True)
class HorizonStatistics:
    horizon: int
    sample_count: int
    mean_directional_return: float | None
    median_directional_return: float | None
    median_mfe: float | None
    median_mae: float | None


@dataclass(frozen=True)
class StatisticsGroup:
    group: str
    event_count: int
    horizons: tuple[HorizonStatistics, ...]
