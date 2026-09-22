"""Bounded, resumable, read-only research history acquisition."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from ..mt5.closure import bar_duration, filter_closed_bars
from ..mt5.errors import ProviderError
from ..mt5.history import HistoryError, RATE_COLUMNS

TIMEFRAMES = ("M15", "H1", "H4", "D1")
VALUES = tuple(c for c in RATE_COLUMNS if c != "time")
SUSPICIOUS_GAP = timedelta(days=7)


def utc_date(value: str) -> datetime:
    """Parse UTC midnight; start inclusive and end exclusive."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("dates must be YYYY-MM-DD in UTC") from exc


def chunks(start: datetime, end: datetime, days: int):
    if days < 1 or end <= start:
        raise ValueError("positive chunk days and end after start required")
    cursor = start
    while cursor < end:
        following = min(cursor + timedelta(days=days), end)
        yield cursor, following
        cursor = following


def year_windows(start: datetime, end: datetime):
    """Calendar-year bounded priming windows clipped to [start, end)."""
    cursor = start
    while cursor < end:
        following = min(datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc), end)
        yield cursor, following
        cursor = following


def normalize(frame: pd.DataFrame | None, timeframe: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=RATE_COLUMNS)
    missing = set(RATE_COLUMNS) - set(frame.columns)
    if missing:
        raise HistoryError(f"missing candle columns: {sorted(missing)}")
    result = frame[RATE_COLUMNS].copy()
    result["time"] = pd.to_datetime(result["time"], utc=True, errors="raise").astype("datetime64[ns, UTC]")
    if result["time"].isna().any():
        raise HistoryError("null candle timestamp")
    for col in VALUES:
        result[col] = pd.to_numeric(result[col], errors="raise").astype("float64")
        values = result[col].dropna() if col in ("real_volume", "spread") else result[col]
        if (col not in ("real_volume", "spread") and result[col].isna().any()) or not values.map(math.isfinite).all():
            raise HistoryError(f"missing or non-finite {col}")
    if ((result["high"] < result[["open", "close"]].max(axis=1)) |
        (result["low"] > result[["open", "close"]].min(axis=1)) |
        (result["high"] < result["low"])).any():
        raise HistoryError("invalid OHLC relationship")
    for col in ("tick_volume", "real_volume", "spread"):
        if (result[col].dropna() < 0).any():
            raise HistoryError(f"negative {col}")
    # Check candle precision without imposing a UTC H4/D1 anchor. A broker
    # can move its session clock historically, including at DST transitions.
    stamps = result["time"].dt
    if ((stamps.second != 0) | (stamps.microsecond != 0) | (stamps.nanosecond != 0) |
        ((stamps.minute % 15) != 0 if timeframe == "M15" else (stamps.minute != 0))).any():
        raise HistoryError(f"timestamps inconsistent with {timeframe} precision")
    return result


def merge(old: pd.DataFrame | None, new: pd.DataFrame, timeframe: str):
    combined = pd.concat((normalize(old, timeframe), normalize(new, timeframe)), ignore_index=True)
    if combined.empty:
        return combined, 0, 0
    duplicates = int(combined["time"].duplicated().sum())
    distinct = combined.drop_duplicates(subset=["time", *VALUES])
    conflicts = int((distinct.groupby("time", sort=False).size() > 1).sum())
    # Latest broker retrieval wins, with every differing timestamp reported.
    result = combined.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
    if result["time"].duplicated().any() or not result["time"].is_monotonic_increasing:
        raise HistoryError("timestamp normalization failed")
    return result, duplicates, conflicts


def fingerprint(frame: pd.DataFrame, timeframe: str) -> str:
    digest = hashlib.sha256()
    for row in normalize(frame, timeframe).itertuples(index=False, name=None):
        values = (pd.Timestamp(row[0]).isoformat(), *(None if pd.isna(v) else float(v) for v in row[1:]))
        digest.update(json.dumps(values, separators=(",", ":"), allow_nan=False).encode() + b"\n")
    return digest.hexdigest()


def gaps(frame: pd.DataFrame, timeframe: str):
    if len(frame) < 2:
        return 0, None, []
    times = pd.to_datetime(frame["time"], utc=True)
    deltas = times.diff()
    notable = [(times.iloc[i-1].isoformat(), times.iloc[i].isoformat(), str(deltas.iloc[i]))
               for i in range(1, len(times)) if deltas.iloc[i] > pd.Timedelta(bar_duration(timeframe))]
    largest = max((pd.Timedelta(item[2]) for item in notable), default=None)
    return len(notable), str(largest) if largest is not None else None, sorted(notable, key=lambda x: pd.Timedelta(x[2]), reverse=True)[:3]


def suspicious_gaps(frame: pd.DataFrame, start: datetime, end: datetime):
    """Interior gaps over seven days intersecting [start, end); market weekends pass."""
    if len(frame) < 2:
        return []
    times = pd.to_datetime(frame["time"], utc=True)
    deltas = times.diff()
    left = times.shift(1)
    mask = (deltas > pd.Timedelta(SUSPICIOUS_GAP)) & (times > pd.Timestamp(start)) & (left < pd.Timestamp(end))
    return [(left.iloc[i].isoformat(), times.iloc[i].isoformat(), str(deltas.iloc[i]))
            for i in range(1, len(times)) if bool(mask.iloc[i])]


def validate_replay_coverage(histories: dict[str, pd.DataFrame], symbol: str,
                             start: datetime | None, end: datetime | None) -> None:
    """Fail closed before research replay/statistics cross an unexplained hole."""
    for timeframe, frame in histories.items():
        if frame is None or frame.empty:
            raise HistoryError(f"No research history for {symbol} {timeframe}; run research-sync first")
        first = pd.Timestamp(frame["time"].iloc[0])
        last_close = pd.Timestamp(frame["time"].iloc[-1]) + bar_duration(timeframe)
        if start is not None and first > pd.Timestamp(start):
            raise HistoryError(f"{symbol} {timeframe} research start boundary is missing")
        if end is not None and last_close < pd.Timestamp(end):
            raise HistoryError(f"{symbol} {timeframe} research end boundary is missing")
        holes = suspicious_gaps(frame, start or first.to_pydatetime(), end or last_close.to_pydatetime())
        if holes:
            raise HistoryError(f"{symbol} {timeframe} research range intersects an unexplained "
                               f"gap over 7 days: {holes[0]}")


def _fetch_window(provider, symbol, timeframe, start, end, broker_now):
    error = None
    for attempt in range(3):
        try:
            fetched = provider.rates_window(symbol, timeframe, start, end)
            error = None
            break
        except ProviderError as exc:
            error = exc
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    if error:
        raise ProviderError(f"{symbol} {timeframe} chunk {start} -> {end}: {error}")
    fetched = normalize(fetched, timeframe)
    fetched = fetched[(fetched["time"] >= pd.Timestamp(start)) &
                      (fetched["time"] < pd.Timestamp(end))].reset_index(drop=True)
    return filter_closed_bars(fetched, timeframe, broker_now)


class ResearchHistoryStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def path_for(self, symbol: str, timeframe: str) -> Path:
        return self.base_dir / symbol / f"{timeframe}.parquet"

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame:
        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return pd.DataFrame(columns=RATE_COLUMNS)
        result = normalize(pd.read_parquet(path), timeframe)
        if result["time"].duplicated().any() or not result["time"].is_monotonic_increasing:
            raise HistoryError(f"stored research history is unordered or duplicated: {path}")
        return result

    def save(self, frame: pd.DataFrame, symbol: str, timeframe: str) -> None:
        result, _, _ = merge(None, frame, timeframe)
        path = self.path_for(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            result.to_parquet(temporary, index=False)
            if fingerprint(pd.read_parquet(temporary), timeframe) != fingerprint(result, timeframe):
                raise HistoryError("Parquet round-trip changed candle values")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Coverage:
    symbol: str
    timeframe: str
    count: int
    earliest: str | None
    latest: str | None
    research_start: str
    research_end: str
    acquired_start: str
    requested_start_reached: bool
    start_reached: bool
    end_reached: bool
    duplicates: int
    conflicts: int
    discontinuities: int
    largest_gap: str | None
    notable_gaps: tuple
    fingerprint: str
    d1_open_utc: dict[str, int]
    empty_chunks: int
    primed_windows: int
    empty_prime_windows: int
    unresolved_empty_chunks: tuple
    suspicious_interior_gaps: tuple
    continuously_usable: bool


def acquire(provider, store: ResearchHistoryStore, symbol: str, timeframe: str,
            research_start: datetime, research_end: datetime, *, warmup_days: int = 180,
            chunk_days: int = 14, force_refresh: bool = False, progress=print) -> Coverage:
    if timeframe not in TIMEFRAMES or warmup_days < 0 or research_end <= research_start:
        raise ValueError("invalid timeframe, warmup or research range")
    acquired_start = research_start - timedelta(days=warmup_days)
    broker_now = provider.tick(symbol).time
    current = store.load(symbol, timeframe)
    duplicate_total = conflict_total = empty_chunks = 0
    primed_windows = empty_prime_windows = 0
    unresolved_empty = []
    prime_counts = {}

    def persist(fetched):
        nonlocal current, duplicate_total, conflict_total
        if fetched.empty:
            return
        merged, duplicate_count, conflict_count = merge(current, fetched, timeframe)
        duplicate_total += duplicate_count
        conflict_total += conflict_count
        if not merged.equals(current):
            store.save(merged, symbol, timeframe)
            current = merged

    # MT5 may return an empty short range before a broader request causes the
    # terminal to load older history. Merge the priming response directly;
    # every row still passes the same range, closure and OHLC validation.
    needs_prime = (force_refresh or current.empty or
                   bool(suspicious_gaps(current, acquired_start, research_end)) or
                   pd.Timestamp(current["time"].iloc[0]) > pd.Timestamp(acquired_start + SUSPICIOUS_GAP) or
                   pd.Timestamp(current["time"].iloc[-1]) + pd.Timedelta(bar_duration(timeframe)) <
                   pd.Timestamp(research_end - SUSPICIOUS_GAP))
    if needs_prime:
        for start, end in year_windows(acquired_start, research_end):
            fetched = _fetch_window(provider, symbol, timeframe, start, end, broker_now)
            primed_windows += 1
            prime_counts[start.year] = len(fetched)
            if fetched.empty:
                empty_prime_windows += 1
            persist(fetched)
            progress(f"{symbol} {timeframe} prime {start:%Y-%m-%d} -> {end:%Y-%m-%d} "
                     f"received {len(fetched):,}, stored {len(current):,}")

    windows = list(chunks(acquired_start, research_end, chunk_days))
    reprimed_years = set()
    for index, (start, end) in enumerate(windows, 1):
        # A boundary span alone is insufficient: a giant interior gap must be
        # fetched even if earliest/latest straddle this entire window.
        if (not force_refresh and not current.empty and
            pd.Timestamp(current["time"].iloc[0]) <= pd.Timestamp(start) and
            pd.Timestamp(current["time"].iloc[-1]) >= pd.Timestamp(end) and
            not suspicious_gaps(current, start, end)):
            continue
        request_start = start - bar_duration(timeframe)  # overlap one candle
        fetched = _fetch_window(provider, symbol, timeframe, request_start, end, broker_now)
        if fetched.empty:
            # Re-prime once per calendar year when a long gap or missing edge
            # makes this empty response suspicious. Ordinary weekend gaps are
            # allowed and never filled.
            suspicious = bool(suspicious_gaps(current, start, end))
            if (not current.empty and
                pd.Timestamp(current["time"].iloc[0]) > pd.Timestamp(end + SUSPICIOUS_GAP)):
                suspicious = True
            if (prime_counts.get(start.year, 0) > 0 and suspicious):
                if start.year not in reprimed_years:
                    year_start = max(acquired_start, datetime(start.year, 1, 1, tzinfo=timezone.utc))
                    year_end = min(research_end, datetime(start.year + 1, 1, 1, tzinfo=timezone.utc))
                    persist(_fetch_window(provider, symbol, timeframe, year_start, year_end, broker_now))
                    reprimed_years.add(start.year)
                fetched = _fetch_window(provider, symbol, timeframe, request_start, end, broker_now)
            if fetched.empty:
                empty_chunks += 1
                if suspicious:
                    unresolved_empty.append((start.isoformat(), end.isoformat()))
        persist(fetched)
        progress(f"{symbol} {timeframe} [{index}/{len(windows)}] {start:%Y-%m-%d} -> {end:%Y-%m-%d} "
                 f"received {len(fetched):,}, stored {len(current):,}")
    n_gap, biggest, notable = gaps(current, timeframe)
    earliest = pd.Timestamp(current["time"].iloc[0]) if not current.empty else None
    latest = pd.Timestamp(current["time"].iloc[-1]) if not current.empty else None
    clocks = Counter(ts.strftime("%H:%M") for ts in pd.to_datetime(current["time"], utc=True)) if timeframe == "D1" else {}
    suspicious = suspicious_gaps(current, research_start, research_end)
    start_reached = earliest is not None and earliest <= pd.Timestamp(research_start)
    end_reached = latest is not None and latest + bar_duration(timeframe) >= research_end
    return Coverage(symbol, timeframe, len(current), earliest.isoformat() if earliest is not None else None,
                    latest.isoformat() if latest is not None else None, research_start.isoformat(),
                    research_end.isoformat(), acquired_start.isoformat(),
                    start_reached,
                    earliest is not None and earliest <= pd.Timestamp(acquired_start),
                    end_reached,
                    duplicate_total, conflict_total, n_gap, biggest, tuple(notable),
                    fingerprint(current, timeframe), dict(clocks), empty_chunks,
                    primed_windows, empty_prime_windows, tuple(unresolved_empty),
                    tuple(suspicious), bool(start_reached and end_reached and not suspicious))
