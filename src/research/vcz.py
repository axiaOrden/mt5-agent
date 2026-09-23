"""Pure, closed-candle replay of Cloudgazer's two VCZ box arrays."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Sequence

import numpy as np
import pandas as pd

from ..mt5.closure import bar_duration
from ..pvsra.models import CandleDirection, PVSRAClassification, PVSRAResult, VolumeSource


class VCZSide(str, Enum):
    BELOW = "BELOW"  # literal Pine direction=0; downward recovery branch
    ABOVE = "ABOVE"  # literal Pine direction=1; upward recovery branch


class VCZStatus(str, Enum):
    REMAINING = "REMAINING"
    FULLY_RECOVERED = "FULLY_RECOVERED"
    DISPLAY_EVICTED = "DISPLAY_EVICTED"


def pvsra_flag(result: PVSRAResult | None) -> int | None:
    """Translate saved PVSRA facts to Pine's color-derived flag."""
    if result is None or result.classification == PVSRAClassification.UNAVAILABLE:
        return None
    if result.candle_direction == CandleDirection.NEUTRAL:
        return -1  # Pine pvsraColor=na for a doji.
    sign = 1 if result.candle_direction == CandleDirection.BULLISH else -1
    magnitude = {PVSRAClassification.NORMAL: 1,
                 PVSRAClassification.ABOVE_AVERAGE: 2,
                 PVSRAClassification.CLIMAX: 3}[result.classification]
    return sign * magnitude


@dataclass(frozen=True)
class VCZZone:
    zone_id: str
    symbol: str
    timeframe: str
    side: VCZSide
    source_bar_open_time: datetime
    source_bar_close_time: datetime
    pvsra_flag: int
    pvsra_classification: PVSRAClassification
    pvsra_candle_direction: CandleDirection
    volume_source: VolumeSource
    volume: float | None
    volume_ma: float | None
    spread: float | None
    spread_ma: float | None
    vwap_displacement: float | None
    vwap_displacement_ma: float | None
    original_bottom: float
    original_top: float
    current_bottom: float
    current_top: float
    created_at: datetime
    created_bar_index: int
    last_updated_at: datetime | None = None
    fully_recovered_at: datetime | None = None
    fully_recovered_bar_index: int | None = None
    display_evicted_at: datetime | None = None
    partial_update_count: int = 0

    @property
    def status(self) -> VCZStatus:
        if self.fully_recovered_at is not None:
            return VCZStatus.FULLY_RECOVERED
        if self.display_evicted_at is not None:
            return VCZStatus.DISPLAY_EVICTED
        return VCZStatus.REMAINING

    @property
    def partially_recovered(self) -> bool:
        return (self.current_bottom != self.original_bottom or
                self.current_top != self.original_top)

    @property
    def original_height(self) -> float:
        return self.original_top - self.original_bottom

    @property
    def remaining_height(self) -> float:
        return self.current_top - self.current_bottom

    @property
    def remaining_fraction(self) -> float | None:
        return self.remaining_height / self.original_height if self.original_height > 0 else None

    @property
    def bars_until_recovery(self) -> int | None:
        return (self.fully_recovered_bar_index - self.created_bar_index
                if self.fully_recovered_bar_index is not None else None)


@dataclass(frozen=True)
class VCZReplay:
    symbol: str
    timeframe: str
    candles_processed: int
    qualifying_pvsra_source_candles: int
    zones: tuple[VCZZone, ...]
    as_of: datetime | None

    @property
    def surviving_zones(self) -> tuple[VCZZone, ...]:
        return tuple(z for z in self.zones if z.status == VCZStatus.REMAINING)

    @property
    def fully_recovered_zones(self) -> tuple[VCZZone, ...]:
        return tuple(z for z in self.zones if z.status == VCZStatus.FULLY_RECOVERED)


def _zone_id(symbol: str, timeframe: str, source_time: datetime,
             flag: int, side: VCZSide) -> str:
    key = f"{symbol}|{timeframe}|{source_time.isoformat()}|{flag}|{side.value}"
    return sha256(key.encode()).hexdigest()[:24]


def _update(zone: VCZZone, side: VCZSide, close: float, high: float, low: float,
            at: datetime, index: int) -> VCZZone:
    """Literal branch/condition order from Pine updateZones."""
    top, bottom = zone.current_top, zone.current_bottom
    if side == VCZSide.ABOVE:
        if close >= top or high >= top:
            return replace(zone, fully_recovered_at=at, fully_recovered_bar_index=index,
                           last_updated_at=at)
        if high > bottom and high < top:
            return replace(zone, current_bottom=high, last_updated_at=at,
                           partial_update_count=zone.partial_update_count + 1)
        if close > bottom and close < top:
            return replace(zone, current_bottom=close, last_updated_at=at,
                           partial_update_count=zone.partial_update_count + 1)
        return zone
    if close <= bottom or low <= bottom:
        return replace(zone, fully_recovered_at=at, fully_recovered_bar_index=index,
                       last_updated_at=at)
    if low > bottom and low < top:
        return replace(zone, current_top=low, last_updated_at=at,
                       partial_update_count=zone.partial_update_count + 1)
    if close > bottom and close < top:
        return replace(zone, current_top=close, last_updated_at=at,
                       partial_update_count=zone.partial_update_count + 1)
    return zone


def replay_vcz(bars: pd.DataFrame, pvsra_results: Sequence[PVSRAResult | None], *,
               symbol: str, timeframe: str, as_of: datetime | None = None,
               max_zones: int | None = None) -> VCZReplay:
    """Replay supplied native bars and existing PVSRA facts in one forward pass.

    `max_zones=None` retains full research history. Explicit `max_zones=20`
    applies Pine's per-array display eviction while still retaining records.
    """
    duration = bar_duration(timeframe)
    if max_zones is not None and max_zones < 1:
        raise ValueError("max_zones must be positive")
    if bars is not None and bars.empty and not pvsra_results:
        return VCZReplay(symbol, timeframe, 0, 0, (), None)
    if bars is None or not {"time", "open", "high", "low", "close"}.issubset(bars):
        raise ValueError("VCZ bars require time, open, high, low, close")
    if len(pvsra_results) != len(bars):
        raise ValueError("one PVSRA result or None per candle is required")
    times = pd.to_datetime(bars["time"], utc=True)
    if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError("VCZ bars require unique increasing timestamps")
    for i, result in enumerate(pvsra_results):
        if result is not None and pd.Timestamp(result.bar_open_time) != times.iloc[i]:
            raise ValueError(f"PVSRA timestamp differs from candle {i}")
    cutoff = pd.Timestamp(as_of) if as_of is not None else None
    if cutoff is not None:
        cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    eligible = len(bars) if cutoff is None else int((times + pd.Timedelta(duration) <= cutoff).sum())
    if eligible == 0:
        return VCZReplay(symbol, timeframe, 0, 0, (), None)
    values = bars[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values[:eligible]).all():
        raise ValueError("VCZ bars contain nonfinite OHLC")
    if ((values[:eligible, 1] < np.maximum(values[:eligible, 0], values[:eligible, 3])) |
        (values[:eligible, 2] > np.minimum(values[:eligible, 0], values[:eligible, 3])) |
        (values[:eligible, 1] < values[:eligible, 2])).any():
        raise ValueError("VCZ bars contain invalid OHLC relationships")

    zones: dict[str, VCZZone] = {}
    active: dict[VCZSide, list[str]] = {VCZSide.BELOW: [], VCZSide.ABOVE: []}
    qualifying = sum(pvsra_flag(result) in (-3, -2, 2, 3)
                     for result in pvsra_results[:eligible])
    for i in range(1, eligible):
        at = (times.iloc[i] + pd.Timedelta(duration)).to_pydatetime()
        source = pvsra_results[i - 1]
        flag = pvsra_flag(source)
        for side in (VCZSide.BELOW, VCZSide.ABOVE):
            if flag in (-3, -2, 2, 3):
                source_time = times.iloc[i - 1].to_pydatetime()
                identity = _zone_id(symbol, timeframe, source_time, flag, side)
                top, bottom = float(values[i - 1, 1]), float(values[i - 1, 2])
                zones[identity] = VCZZone(
                    zone_id=identity, symbol=symbol, timeframe=timeframe,
                    side=side, source_bar_open_time=source_time,
                    source_bar_close_time=(times.iloc[i - 1] + pd.Timedelta(duration)).to_pydatetime(),
                    pvsra_flag=flag, pvsra_classification=source.classification,
                    pvsra_candle_direction=source.candle_direction,
                    volume_source=source.volume_source, volume=source.volume,
                    volume_ma=source.volume_ma, spread=source.spread,
                    spread_ma=source.spread_ma,
                    vwap_displacement=source.vwap_displacement,
                    vwap_displacement_ma=source.vwap_displacement_ma,
                    original_bottom=bottom, original_top=top,
                    current_bottom=bottom, current_top=top,
                    created_at=at, created_bar_index=i)
                active[side].insert(0, identity)
            slots = tuple(active[side])  # Pine's pre-clean array, newest first.
            for identity in slots:
                zones[identity] = _update(zones[identity], side, float(values[i, 3]),
                                          float(values[i, 1]), float(values[i, 2]), at, i)
            if max_zones is not None and len(slots) > max_zones:
                oldest = slots[-1]
                if zones[oldest].status == VCZStatus.REMAINING:
                    zones[oldest] = replace(zones[oldest], display_evicted_at=at)
            active[side] = [identity for identity in active[side]
                            if zones[identity].status == VCZStatus.REMAINING]
    return VCZReplay(symbol, timeframe, eligible, qualifying, tuple(zones.values()),
                     (times.iloc[eligible - 1] + pd.Timedelta(duration)).to_pydatetime())


def vcz_as_of(bars: pd.DataFrame, pvsra_results: Sequence[PVSRAResult | None], *,
              symbol: str, timeframe: str, as_of: datetime,
              max_zones: int | None = None) -> VCZReplay:
    return replay_vcz(bars, pvsra_results, symbol=symbol, timeframe=timeframe,
                      as_of=as_of, max_zones=max_zones)
