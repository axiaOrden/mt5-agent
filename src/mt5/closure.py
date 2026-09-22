"""Closed-candle determination.

Broker/MT5 bar timestamps are authoritative. Closure is decided purely from
the bar's own opening timestamp plus the timeframe duration, compared against
a broker-time "now" (the latest tick time from MT5). The developer machine's
local timezone is never consulted, and no assumption is made about which
wall-clock hour a timeframe closes at.

    A bar with opening timestamp ``t`` on a timeframe of duration ``d`` is
    closed iff ``t + d <= broker_now``.

This works uniformly for M15/H1/H4/D1 (and any other timeframe) without
knowing the broker's bar-grid alignment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Canonical bar durations. MN1 is intentionally not a fixed 30-day month:
# closure for monthly bars must be derived from broker timestamps, never
# assumed from a constant.
_TIMEFRAME_DELTA = {
    "M1": timedelta(minutes=1),
    "M5": timedelta(minutes=5),
    "M15": timedelta(minutes=15),
    "M30": timedelta(minutes=30),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D1": timedelta(days=1),
    "W1": timedelta(weeks=1),
    "MN1": timedelta(days=30),
}

SUPPORTED_TIMEFRAMES = tuple(_TIMEFRAME_DELTA.keys())


def bar_duration(timeframe: str) -> timedelta:
    """Duration of one bar on ``timeframe``."""
    if timeframe not in _TIMEFRAME_DELTA:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return _TIMEFRAME_DELTA[timeframe]


def is_bar_closed(bar_open_time: datetime, timeframe: str, broker_now: datetime) -> bool:
    """True when the bar opening at ``bar_open_time`` has completed by ``broker_now``.

    ``broker_now`` must be broker time (e.g. the latest tick timestamp), not
    the local machine clock.
    """
    t = _as_utc(bar_open_time)
    now = _as_utc(broker_now)
    return t + bar_duration(timeframe) <= now


def filter_closed_bars(df: pd.DataFrame, timeframe: str, broker_now: datetime) -> pd.DataFrame:
    """Keep only bars that have completed by ``broker_now``.

    Any forming bar (and any stale snapshot of a bar that never completed)
    is dropped. The result is sorted chronologically.
    """
    if df is None or df.empty or "time" not in df.columns:
        return df
    duration = bar_duration(timeframe)
    now = _as_utc(broker_now)
    times = pd.to_datetime(df["time"], utc=True)
    closed = times + pd.Timedelta(duration) <= pd.Timestamp(now)
    return df[closed].reset_index(drop=True)


def latest_closed_bar_open(now: datetime, timeframe: str) -> datetime:
    """Opening timestamp of the latest bar that is closed at ``now``.

    Computed on the UTC grid: floor ``now`` to the timeframe duration, then
    step back one bar. Used by the mock provider to generate closed bars
    only; real brokers never need this (their timestamps are authoritative).
    """
    d = bar_duration(timeframe)
    now = _as_utc(now)
    offset = (now - _EPOCH) % d
    floored = now - offset
    return floored - d


def latest_closed_bar_timestamp(df: pd.DataFrame, timeframe: str, broker_now: datetime) -> Optional[datetime]:
    """Latest closed bar opening timestamp in ``df`` (None when none closed)."""
    if df is None or df.empty or "time" not in df.columns:
        return None
    closed = filter_closed_bars(df, timeframe, broker_now)
    if closed.empty:
        return None
    return pd.Timestamp(closed["time"].iloc[-1]).to_pydatetime()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
