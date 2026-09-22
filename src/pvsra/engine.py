"""Exact Cloudgazer PVSRA candle classification over deterministic history."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from ..mt5.closure import filter_closed_bars
from ..signals.vwap_events import broker_session_anchors, session_vwap
from .models import CandleDirection, PVSRAClassification, PVSRAResult, VolumeSource


def analyze_pvsra(
    df: pd.DataFrame,
    timeframe: str,
    *,
    bar_open_time: datetime | None = None,
    daily_opens: pd.Series | None = None,
    period: int = 20,
    climax_multiplier: float = 2.0,
    above_multiplier: float = 1.2,
) -> PVSRAResult | None:
    """Classify one historical bar using only data through that bar.

    ``df`` must already contain validated closed bars. When ``bar_open_time``
    is supplied, later rows are removed before volume-source selection, VWAP,
    and moving-average calculation, preserving historical reproducibility.
    """
    if df is None or df.empty:
        return None
    if period < 1:
        raise ValueError("period must be positive")
    bars = df.sort_values("time").reset_index(drop=True).copy()
    bars["time"] = pd.to_datetime(bars["time"], utc=True)
    if bar_open_time is not None:
        target = pd.Timestamp(bar_open_time)
        target = target.tz_localize("UTC") if target.tzinfo is None else target.tz_convert("UTC")
        bars = bars[bars["time"] <= target].reset_index(drop=True)
        if bars.empty or bars["time"].iloc[-1] != target:
            return None
    row = bars.iloc[-1]
    source, volume = _select_volume(bars)
    direction = _candle_direction(float(row["open"]), float(row["close"]))
    bar_time = pd.Timestamp(row["time"]).to_pydatetime()
    spread_series = bars["high"].astype(float) - bars["low"].astype(float)
    spread = _finite_or_none(spread_series.iloc[-1])
    spread_ma = _finite_or_none(spread_series.rolling(period, min_periods=period).mean().iloc[-1])

    if daily_opens is not None and len(daily_opens) > 0:
        anchors = pd.to_datetime(daily_opens, utc=True)
        anchors = anchors[anchors <= bars["time"].iloc[-1]]
        vwap_series = session_vwap(bars, anchors)
    else:
        # Broker D1 boundaries are part of the audited VWAP definition. Do
        # not silently substitute UTC dates when confirmation is requested.
        vwap_series = pd.Series(float("nan"), index=bars.index)
    vwap = _finite_or_none(vwap_series.iloc[-1])
    displacement_series = (bars["close"].astype(float) - vwap_series).abs()
    displacement = _finite_or_none(displacement_series.iloc[-1])
    displacement_ma = _finite_or_none(
        displacement_series.rolling(period, min_periods=period).mean().iloc[-1]
    )

    selected_volume = _finite_or_none(volume.iloc[-1]) if volume is not None else None
    volume_ma = _finite_or_none(
        volume.rolling(period, min_periods=period).mean().iloc[-1]
    ) if volume is not None else None
    available = all(value is not None for value in (
        selected_volume, volume_ma, spread, spread_ma, vwap, displacement, displacement_ma
    )) and source != VolumeSource.UNAVAILABLE and volume_ma > 0

    classification = classify_pvsra(
        selected_volume, volume_ma, spread, spread_ma, displacement, displacement_ma,
        climax_multiplier=climax_multiplier, above_multiplier=above_multiplier,
    ) if available else PVSRAClassification.UNAVAILABLE

    return PVSRAResult(
        bar_open_time=bar_time,
        classification=classification,
        candle_direction=direction,
        volume_source=source,
        volume=selected_volume,
        volume_ma=volume_ma,
        volume_ratio=_ratio(selected_volume, volume_ma),
        spread=spread,
        spread_ma=spread_ma,
        spread_ratio=_ratio(spread, spread_ma),
        vwap=vwap,
        vwap_displacement=displacement,
        vwap_displacement_ma=displacement_ma,
        vwap_displacement_ratio=_ratio(displacement, displacement_ma),
    )


def classify_pvsra(
    volume: float,
    volume_ma: float,
    spread: float,
    spread_ma: float,
    displacement: float,
    displacement_ma: float,
    *,
    climax_multiplier: float = 2.0,
    above_multiplier: float = 1.2,
) -> PVSRAClassification:
    """Apply the Pine boolean precedence to already-valid measurements."""
    climax_volume = volume >= volume_ma * climax_multiplier
    spread_expansion = spread >= spread_ma * 1.5
    vwap_expansion = displacement >= displacement_ma * 1.5
    climax = climax_volume and (spread_expansion or vwap_expansion)
    above = not climax and volume >= volume_ma * above_multiplier
    if climax:
        return PVSRAClassification.CLIMAX
    if above:
        return PVSRAClassification.ABOVE_AVERAGE
    return PVSRAClassification.NORMAL


def pvsra_as_of(
    df: pd.DataFrame,
    timeframe: str,
    as_of: datetime,
    *,
    daily_bars: pd.DataFrame | None = None,
    period: int = 20,
) -> PVSRAResult | None:
    """Classify the latest candle closed at ``as_of`` with no lookahead."""
    closed = filter_closed_bars(df, timeframe, as_of)
    if closed is None or closed.empty:
        return None
    anchors = None
    if daily_bars is not None and not daily_bars.empty:
        closed_daily = filter_closed_bars(daily_bars, "D1", as_of)
        anchors = broker_session_anchors(closed_daily, pd.Timestamp(closed["time"].iloc[-1]))
    return analyze_pvsra(closed, timeframe, daily_opens=anchors, period=period)


def _select_volume(bars: pd.DataFrame) -> tuple[VolumeSource, pd.Series | None]:
    for column, source in (
        ("real_volume", VolumeSource.REAL_VOLUME),
        ("tick_volume", VolumeSource.TICK_VOLUME),
    ):
        if column not in bars:
            continue
        values = pd.to_numeric(bars[column], errors="coerce").astype(float)
        if values.notna().all() and (values >= 0).all() and (values > 0).any():
            return source, values
    return VolumeSource.UNAVAILABLE, None


def _candle_direction(open_: float, close: float) -> CandleDirection:
    if close > open_:
        return CandleDirection.BULLISH
    if close < open_:
        return CandleDirection.BEARISH
    return CandleDirection.NEUTRAL


def _finite_or_none(value) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def _ratio(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None or baseline == 0:
        return None
    return value / baseline
