"""Immutable facts and historical Cloudgazer signal state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    TK_CROSS_BULLISH = "TK_CROSS_BULLISH"
    TK_CROSS_BEARISH = "TK_CROSS_BEARISH"
    VWAP_CROSS_BULLISH = "VWAP_CROSS_BULLISH"
    VWAP_CROSS_BEARISH = "VWAP_CROSS_BEARISH"
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"


class CloudgazerState(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class SignalEvent:
    symbol: str
    timeframe: str
    bar_open_time: datetime
    event_type: EventType

    @property
    def identity(self) -> tuple[str, str, datetime, EventType]:
        return self.symbol, self.timeframe, self.bar_open_time, self.event_type


@dataclass(frozen=True)
class CloudgazerTransition:
    bar_open_time: datetime
    raw_events: tuple[SignalEvent, ...]
    winning_event: SignalEvent | None
    suppressed_events: tuple[SignalEvent, ...]
    previous_state: CloudgazerState
    new_state: CloudgazerState
    label: str | None
