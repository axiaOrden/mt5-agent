"""Ichimoku indicator — pure, inspectable implementation.

Standard parameters:
    Tenkan:       9
    Kijun:       26
    Senkou B:    52
    Displacement: 26

All calculations are plain pandas rolling operations; no opaque TA library.

Indexing / alignment semantics
------------------------------
Let ``t`` be the index of the current (latest closed) candle and
``D = displacement``.

* ``tenkan_sen[t]``, ``kijun_sen[t]`` — current values at ``t``.
* ``senkou_span_a[t]`` / ``senkou_span_b[t]`` — the Kumo located AT candle
  ``t`` (plotting-aligned): computed from values 26 bars earlier and shifted
  forward by ``D``. These are the correct spans for "current price vs the
  Kumo at the current candle".
* ``senkou_span_a_projected[t]`` / ``senkou_span_b_projected[t]`` — the Kumo
  that will be plotted at ``t + D``: computed from the CURRENT candle's
  Tenkan/Kijun and the current 52-bar midpoint, unshifted. These are the
  correct spans for classifying the projected/future cloud.
* ``chikou_span[t]`` — the close displaced backward by ``D``; the value
  plotted at ``t - D`` is ``close[t]``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IchimokuResult:
    """Ichimoku values aligned to the input index.

    ``senkou_span_a`` / ``senkou_span_b`` are plotting-aligned (shifted
    forward by ``displacement``): row ``i`` holds the cloud located at
    candle ``i``, computed from values at ``i - displacement``.

    ``senkou_span_a_projected`` / ``senkou_span_b_projected`` are unshifted:
    row ``i`` holds the cloud that will be plotted at candle
    ``i + displacement``, computed from the current candle's values.

    ``chikou_span`` is the close shifted backward by ``displacement``:
    row ``i`` holds ``close[i + displacement]``.
    """

    tenkan_sen: pd.Series
    kijun_sen: pd.Series
    senkou_span_a: pd.Series
    senkou_span_b: pd.Series
    senkou_span_a_projected: pd.Series
    senkou_span_b_projected: pd.Series
    chikou_span: pd.Series

    @property
    def displacement(self) -> int:
        return 26


def _midpoint(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    """(highest high + lowest low) / 2 over ``period`` bars."""
    return (high.rolling(period).max() + low.rolling(period).min()) / 2.0


def ichimoku(
    df: pd.DataFrame,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    displacement: int = 26,
) -> IchimokuResult:
    """Compute Ichimoku components from an OHLC DataFrame.

    Requires columns: high, low, close. Rows must be chronological.
    """
    if df.empty:
        raise ValueError("ichimoku: empty DataFrame")
    for col in ("high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"ichimoku: missing column {col!r}")

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    tenkan_sen = _midpoint(high, low, tenkan)
    kijun_sen = _midpoint(high, low, kijun)

    # Current-location (plotting-aligned) cloud: shifted forward by D.
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2.0).shift(displacement)
    senkou_span_b = _midpoint(high, low, senkou_b).shift(displacement)

    # Projected cloud: unshifted current calculations, plotted at t + D.
    senkou_span_a_projected = (tenkan_sen + kijun_sen) / 2.0
    senkou_span_b_projected = _midpoint(high, low, senkou_b)

    chikou_span = close.shift(-displacement)

    return IchimokuResult(
        tenkan_sen=tenkan_sen,
        kijun_sen=kijun_sen,
        senkou_span_a=senkou_span_a,
        senkou_span_b=senkou_span_b,
        senkou_span_a_projected=senkou_span_a_projected,
        senkou_span_b_projected=senkou_span_b_projected,
        chikou_span=chikou_span,
    )


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing) for volatility normalization."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()
