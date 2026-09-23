"""Causal PVSRA prefix measurements reused across research event snapshots."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..pvsra.engine import (_candle_direction, _finite_or_none, _ratio,
                            classify_pvsra)
from ..pvsra.models import PVSRAClassification, PVSRAResult, VolumeSource
from ..signals.vwap_events import session_vwap


class PVSRAIndex:
    """Precompute the same rolling series used by ``analyze_pvsra``.

    Source selection remains prefix-dependent: real volume is preferred only
    after a positive value has appeared and while every earlier value is
    usable. Tick volume is the same fallback as the public engine.
    """

    def __init__(self, bars: pd.DataFrame, daily_opens: pd.Series, period: int = 20):
        self.bars = bars
        self.period = period
        self.open_values = bars["open"].to_numpy()
        self.close_values = bars["close"].to_numpy()
        self.times = bars["time"].to_numpy()
        spread = bars["high"].astype(float) - bars["low"].astype(float)
        self.spread = spread.to_numpy()
        self.spread_ma = spread.rolling(period, min_periods=period).mean().to_numpy()

        self.volumes = {}
        for column, source in (("real_volume", VolumeSource.REAL_VOLUME),
                               ("tick_volume", VolumeSource.TICK_VOLUME)):
            if column not in bars:
                continue
            values = pd.to_numeric(bars[column], errors="coerce").astype(float)
            raw = values.to_numpy()
            valid = np.logical_and.accumulate(~np.isnan(raw) & (raw >= 0))
            positive = np.logical_or.accumulate(raw > 0)
            rolling = values.rolling(period, min_periods=period).mean().to_numpy()
            self.volumes[source] = (raw, rolling, valid & positive)

        if daily_opens is not None and len(daily_opens) > 0:
            vwap = session_vwap(bars, daily_opens)
        else:
            vwap = pd.Series(float("nan"), index=bars.index)
        self.vwap = vwap.to_numpy()
        displacement = (bars["close"].astype(float) - vwap).abs()
        self.displacement = displacement.to_numpy()
        self.displacement_ma = displacement.rolling(period, min_periods=period).mean().to_numpy()

    def at(self, position: int) -> PVSRAResult:
        source = VolumeSource.UNAVAILABLE
        volume = volume_ma = None
        for candidate in (VolumeSource.REAL_VOLUME, VolumeSource.TICK_VOLUME):
            record = self.volumes.get(candidate)
            if record is not None and bool(record[2][position]):
                source = candidate
                volume = _finite_or_none(record[0][position])
                volume_ma = _finite_or_none(record[1][position])
                break

        spread = _finite_or_none(self.spread[position])
        spread_ma = _finite_or_none(self.spread_ma[position])
        vwap = _finite_or_none(self.vwap[position])
        displacement = _finite_or_none(self.displacement[position])
        displacement_ma = _finite_or_none(self.displacement_ma[position])
        available = all(value is not None for value in (
            volume, volume_ma, spread, spread_ma, vwap, displacement, displacement_ma
        )) and source != VolumeSource.UNAVAILABLE and volume_ma > 0
        classification = classify_pvsra(
            volume, volume_ma, spread, spread_ma, displacement, displacement_ma,
        ) if available else PVSRAClassification.UNAVAILABLE
        return PVSRAResult(
            bar_open_time=pd.Timestamp(self.times[position]).to_pydatetime(),
            classification=classification,
            candle_direction=_candle_direction(float(self.open_values[position]),
                                                float(self.close_values[position])),
            volume_source=source,
            volume=volume,
            volume_ma=volume_ma,
            volume_ratio=_ratio(volume, volume_ma),
            spread=spread,
            spread_ma=spread_ma,
            spread_ratio=_ratio(spread, spread_ma),
            vwap=vwap,
            vwap_displacement=displacement,
            vwap_displacement_ma=displacement_ma,
            vwap_displacement_ratio=_ratio(displacement, displacement_ma),
        )
