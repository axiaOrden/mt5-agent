"""Historical market-data synchronization with local Parquet storage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .closure import SUPPORTED_TIMEFRAMES, bar_duration, filter_closed_bars
from .errors import ProviderError

logger = logging.getLogger(__name__)

RATE_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


class HistoryError(RuntimeError):
    """Raised when historical data fails validation."""


@dataclass(frozen=True)
class SyncResult:
    symbol: str
    timeframe: str
    bars_before: int
    bars_after: int
    added: int

    @property
    def bars(self) -> int:
        return self.bars_after


def fetch_rates(mt5: Any, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """Fetch the most recent ``count`` completed bars from MT5.

    Position 1 is the latest completed bar (position 0 is the currently
    forming candle, which must never enter strategy history).
    """
    tf = _timeframe_to_mt5(timeframe)
    raw = mt5.copy_rates_from_pos(symbol, tf, 1, count)
    if raw is None or len(raw) == 0:
        raise ProviderError(f"No historical data for {symbol} {timeframe}: {mt5.last_error()}")
    return _to_frame(raw)


def fetch_rates_since(mt5: Any, symbol: str, timeframe: str, since: datetime, count: int) -> pd.DataFrame:
    """Fetch bars from ``since`` (UTC) up to now from MT5.

    Range retrieval can include the currently forming bar; it is explicitly
    filtered out using the latest tick time as broker "now".
    """
    tf = _timeframe_to_mt5(timeframe)
    since_utc = since.astimezone(timezone.utc) if since.tzinfo else since.replace(tzinfo=timezone.utc)
    raw = mt5.copy_rates_range(symbol, tf, since_utc, datetime.now(timezone.utc))
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=RATE_COLUMNS)
    df = _to_frame(raw)
    tick = mt5.symbol_info_tick(symbol)
    if tick is not None:
        broker_now = pd.Timestamp(tick.time, unit="s", tz="UTC").to_pydatetime()
        df = filter_closed_bars(df, timeframe, broker_now)
    return df


def fetch_rates_window(mt5: Any, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Read a bounded [start, end) window; close filtering remains broker-tick based."""
    start_ts = pd.Timestamp(start).tz_convert("UTC")
    end_ts = pd.Timestamp(end).tz_convert("UTC")
    raw = mt5.copy_rates_range(
        symbol, _timeframe_to_mt5(timeframe), start_ts.to_pydatetime(),
        (end_ts - pd.Timedelta(seconds=1)).to_pydatetime(),
    )
    if raw is None:
        raise ProviderError(f"MT5 range retrieval failed for {symbol} {timeframe}: {mt5.last_error()}")
    if len(raw) == 0:
        return pd.DataFrame(columns=RATE_COLUMNS)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise ProviderError(f"tick unavailable for {symbol}; cannot verify closure")
    return filter_closed_bars(
        _to_frame(raw), timeframe,
        pd.Timestamp(tick.time, unit="s", tz="UTC").to_pydatetime(),
    )


def _to_frame(raw: Any) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[RATE_COLUMNS]


def _timeframe_to_mt5(timeframe: str) -> int:
    mapping = {
        "M1": 1, "M5": 5, "M15": 15, "M30": 30,
        "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769, "MN1": 49153,
    }
    if timeframe not in mapping:
        raise ProviderError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]


def timeframe_delta(timeframe: str) -> timedelta:
    """Duration of one bar on ``timeframe`` (alias of closure.bar_duration)."""
    return bar_duration(timeframe)


def validate_history(df: pd.DataFrame, symbol: str, timeframe: str) -> None:
    """Validate timestamps, duplicates, OHLC sanity and ordering. Raises HistoryError."""
    if df is None or df.empty:
        raise HistoryError(f"Empty history for {symbol} {timeframe}")
    if "time" not in df.columns:
        raise HistoryError(f"Missing time column for {symbol} {timeframe}")

    times = df["time"]
    if times.isna().any():
        raise HistoryError(f"Null timestamps for {symbol} {timeframe}")
    if not pd.api.types.is_datetime64_any_dtype(times):
        raise HistoryError(f"time column is not datetime for {symbol} {timeframe}")
    if times.duplicated().any():
        raise HistoryError(f"Duplicate bars for {symbol} {timeframe}")
    if not times.is_monotonic_increasing:
        raise HistoryError(f"Bars not chronological for {symbol} {timeframe}")

    for col in ("open", "high", "low", "close"):
        if df[col].isna().any():
            raise HistoryError(f"Null {col} values for {symbol} {timeframe}")
    bad_high = (df["high"] < df[["open", "close"]].max(axis=1)) | (df["high"] < df["low"])
    bad_low = (df["low"] > df[["open", "close"]].min(axis=1)) | (df["low"] > df["high"])
    if bad_high.any() or bad_low.any():
        raise HistoryError(f"Invalid OHLC relationship for {symbol} {timeframe}")
    if (df["tick_volume"] < 0).any():
        raise HistoryError(f"Negative volume for {symbol} {timeframe}")


def merge_history(local: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    """Merge local and newly fetched bars: deduplicate on time, sort chronologically.

    Time columns are normalized to a single resolution (datetime64[ns, UTC])
    before concatenation — pandas 3.0 keeps per-source resolutions (e.g. ms
    from Parquet vs s from unix timestamps) and DataFrame concat of mixed
    resolutions degrades the column to object dtype.
    """
    frames = [f for f in (local, new) if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=RATE_COLUMNS)
    normalized = []
    for f in frames:
        f = f.copy()
        if "time" in f.columns:
            f["time"] = f["time"].astype("datetime64[ns, UTC]")
        normalized.append(f)
    merged = pd.concat(normalized, ignore_index=True)
    merged = merged.drop_duplicates(subset="time", keep="last")
    merged = merged.sort_values("time").reset_index(drop=True)
    return merged


class HistoryStore:
    """Parquet-backed local store for per-symbol/per-timeframe OHLC history."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def path_for(self, symbol: str, timeframe: str) -> Path:
        return self.base_dir / symbol / f"{timeframe}.parquet"

    def load(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True).astype("datetime64[ns, UTC]")
        return df

    def save(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None:
        path = self.path_for(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    def sync(self, provider: Any, symbol: str, timeframe: str, bars: int) -> SyncResult:
        """Synchronize history for one symbol/timeframe.

        First run downloads ``bars`` bars. Later runs read the latest local
        timestamp, request newer bars, merge, deduplicate, sort and save.

        Closed-candle invariant: after merging, any bar that has not
        completed by broker time (latest tick) is dropped. This both keeps
        the forming candle out of strategy history and repairs stale
        previously-forming snapshots left in the cache by older versions.
        """
        local = self.load(symbol, timeframe)
        bars_before = 0 if local is None else len(local)

        if local is not None and len(local) >= bars:
            since = local["time"].max() - 2 * timeframe_delta(timeframe)
            new = provider.rates_since(symbol, timeframe, since, bars)
            merged = merge_history(local, new)
        else:
            new = provider.rates(symbol, timeframe, bars)
            merged = merge_history(local, new)

        if merged.empty:
            raise HistoryError(f"No data available for {symbol} {timeframe}")

        merged = self._drop_forming_bars(provider, merged, symbol, timeframe)

        if merged.empty:
            raise HistoryError(f"No closed bars available for {symbol} {timeframe}")

        validate_history(merged, symbol, timeframe)
        self.save(merged, symbol, timeframe)
        added = len(merged) - bars_before
        logger.info(
            "history sync %s %s: %d -> %d bars (+%d)",
            symbol, timeframe, bars_before, len(merged), added,
        )
        return SyncResult(symbol, timeframe, bars_before, len(merged), added)

    def latest_closed_bar_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Latest closed bar opening timestamp in the local cache (None if absent).

        This is the anchor a future event-driven scheduler will poll: when
        the broker's latest closed bar timestamp advances past this value,
        a new sync + analysis is due for ``symbol × timeframe``.
        """
        df = self.load(symbol, timeframe)
        if df is None or df.empty:
            return None
        return pd.Timestamp(df["time"].iloc[-1]).to_pydatetime()

    @staticmethod
    def _drop_forming_bars(provider: Any, merged: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        """Drop bars not yet closed at broker time; tolerate providers without ticks."""
        try:
            tick = provider.tick(symbol)
        except ProviderError:
            logger.warning(
                "tick unavailable for %s; skipping closed-bar filter (data assumed closed)",
                symbol,
            )
            return merged
        broker_now = tick.time
        return filter_closed_bars(merged, timeframe, broker_now)
