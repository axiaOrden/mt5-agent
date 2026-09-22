"""Cloudgazer close-based Ichimoku, separate from standard market-state Ichimoku."""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from .models import EventType


@dataclass(frozen=True)
class CloudgazerIchimoku:
    tenkan: pd.Series
    kijun: pd.Series
    span_a: pd.Series
    span_b: pd.Series


def cloudgazer_ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, span_b: int = 52) -> CloudgazerIchimoku:
    if min(tenkan, kijun, span_b) < 1:
        raise ValueError("Ichimoku periods must be positive")
    close = df["close"].astype(float)
    midpoint = lambda n: (close.rolling(n, min_periods=n).min() + close.rolling(n, min_periods=n).max()) / 2
    t, k = midpoint(tenkan), midpoint(kijun)
    return CloudgazerIchimoku(t, k, (t + k) / 2, midpoint(span_b))


def tk_cross(previous_tenkan: float, previous_kijun: float, current_tenkan: float, current_kijun: float) -> EventType | None:
    if any(pd.isna(v) for v in (previous_tenkan, previous_kijun, current_tenkan, current_kijun)):
        return None
    if previous_tenkan <= previous_kijun and current_tenkan > current_kijun:
        return EventType.TK_CROSS_BULLISH
    if previous_tenkan >= previous_kijun and current_tenkan < current_kijun:
        return EventType.TK_CROSS_BEARISH
    return None
