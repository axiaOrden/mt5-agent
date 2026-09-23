"""Immutable Phase 1.8C PVSRA activity observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PVSRAClassification(str, Enum):
    NORMAL = "NORMAL"
    ABOVE_AVERAGE = "ABOVE_AVERAGE"
    CLIMAX = "CLIMAX"
    UNAVAILABLE = "UNAVAILABLE"


class CandleDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class VolumeSource(str, Enum):
    REAL_VOLUME = "REAL_VOLUME"
    TICK_VOLUME = "TICK_VOLUME"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class PVSRAResult:
    bar_open_time: datetime
    classification: PVSRAClassification
    candle_direction: CandleDirection
    volume_source: VolumeSource
    volume: float | None
    volume_ma: float | None
    volume_ratio: float | None
    spread: float | None
    spread_ma: float | None
    spread_ratio: float | None
    vwap: float | None
    vwap_displacement: float | None
    vwap_displacement_ma: float | None
    vwap_displacement_ratio: float | None
