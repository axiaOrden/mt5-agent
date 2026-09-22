"""Unit tests for historical-data merge, deduplication and validation."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.mt5.history import (
    HistoryError,
    HistoryStore,
    RATE_COLUMNS,
    merge_history,
    validate_history,
)


def _bars(n: int, start: datetime, freq: str = "15min") -> pd.DataFrame:
    times = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "tick_volume": [100] * n,
            "spread": [1.0] * n,
            "real_volume": [0] * n,
        }
    )


def test_merge_deduplicates_overlap():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    local = _bars(10, start)
    new = _bars(6, start + timedelta(minutes=15 * 7))  # overlaps last 3 local bars
    merged = merge_history(local, new)
    assert len(merged) == 13
    assert merged["time"].is_unique
    assert merged["time"].is_monotonic_increasing


def test_merge_sorts_chronologically():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    local = _bars(5, start)
    new = _bars(5, start + timedelta(minutes=15 * 10))
    merged = merge_history(new, local)  # passed out of order
    assert merged["time"].is_monotonic_increasing
    assert len(merged) == 10


def test_merge_keeps_newest_on_conflict():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    local = _bars(3, start)
    new = _bars(3, start)
    new["close"] = new["close"] + 1000.0
    merged = merge_history(local, new)
    assert len(merged) == 3
    assert (merged["close"] > 1000).all()


def test_merge_empty_inputs():
    assert merge_history(None, None).empty
    assert merge_history(None, _bars(2, datetime(2024, 1, 1, tzinfo=timezone.utc))).empty is False


def test_validate_ok():
    df = _bars(10, datetime(2024, 1, 1, tzinfo=timezone.utc))
    validate_history(df, "XAUUSDm", "M15")  # should not raise


def test_validate_duplicate_bars_raise():
    df = _bars(10, datetime(2024, 1, 1, tzinfo=timezone.utc))
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(HistoryError, match="Duplicate"):
        validate_history(df, "XAUUSDm", "M15")


def test_validate_non_chronological_raises():
    df = _bars(10, datetime(2024, 1, 1, tzinfo=timezone.utc))
    df = df.iloc[::-1].reset_index(drop=True)
    with pytest.raises(HistoryError, match="chronological"):
        validate_history(df, "XAUUSDm", "M15")


def test_validate_null_ohlc_raises():
    df = _bars(10, datetime(2024, 1, 1, tzinfo=timezone.utc))
    df.loc[3, "close"] = None
    with pytest.raises(HistoryError, match="Null close"):
        validate_history(df, "XAUUSDm", "M15")


def test_validate_bad_ohlc_relationship_raises():
    df = _bars(10, datetime(2024, 1, 1, tzinfo=timezone.utc))
    df.loc[3, "high"] = df.loc[3, "low"] - 5.0
    with pytest.raises(HistoryError, match="OHLC"):
        validate_history(df, "XAUUSDm", "M15")


def test_validate_empty_raises():
    with pytest.raises(HistoryError, match="Empty"):
        validate_history(pd.DataFrame(), "XAUUSDm", "M15")


class _FakeProvider:
    """Minimal provider stub for sync tests."""

    def __init__(self, bars: pd.DataFrame) -> None:
        self._bars = bars

    def rates(self, symbol, timeframe, count):
        return self._bars.tail(count).reset_index(drop=True)

    def rates_since(self, symbol, timeframe, since, count):
        return self._bars[self._bars["time"] >= pd.Timestamp(since)].reset_index(drop=True)

    def tick(self, symbol):
        from src.models import Tick

        last = self._bars["time"].iloc[-1]
        return Tick(
            symbol=symbol,
            time=(last + pd.Timedelta(minutes=30)).to_pydatetime(),
            bid=1.0,
            ask=1.0,
            last=1.0,
            volume=1.0,
        )


def test_sync_first_run_downloads(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    provider = _FakeProvider(_bars(100, start))
    store = HistoryStore(tmp_path)
    result = store.sync(provider, "XAUUSDm", "M15", 100)
    assert result.bars_before == 0
    assert result.bars_after == 100
    assert result.added == 100
    assert store.path_for("XAUUSDm", "M15").exists()


def test_sync_incremental_merges_new_bars(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    provider = _FakeProvider(_bars(100, start))
    store = HistoryStore(tmp_path)
    store.sync(provider, "XAUUSDm", "M15", 100)

    # Provider now has 110 bars; local has 100.
    provider._bars = _bars(110, start)
    result = store.sync(provider, "XAUUSDm", "M15", 100)
    assert result.bars_before == 100
    assert result.bars_after == 110
    assert result.added == 10

    loaded = store.load("XAUUSDm", "M15")
    assert len(loaded) == 110
    assert loaded["time"].is_unique
    assert loaded["time"].is_monotonic_increasing


def test_sync_roundtrip_parquet(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    provider = _FakeProvider(_bars(50, start))
    store = HistoryStore(tmp_path)
    store.sync(provider, "EURUSDm", "H1", 50)
    loaded = store.load("EURUSDm", "H1")
    assert list(loaded.columns) == RATE_COLUMNS
    assert loaded["time"].dt.tz is not None
