from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from src.mt5.history import HistoryError, RATE_COLUMNS
from src.mt5.errors import ProviderError
from src.mt5.remote import RemoteMT5Provider
from src.research.acquisition import ResearchHistoryStore, acquire, chunks, fingerprint, merge, normalize

UTC = timezone.utc


def bars(*times, close=2.0):
    return pd.DataFrame([dict(time=t, open=1.0, high=max(2.0, close), low=1.0,
                              close=close, tick_volume=4, spread=1, real_volume=0)
                         for t in times], columns=RATE_COLUMNS)


def test_chunk_edges_and_overlap_merge():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=5)
    assert list(chunks(start, end, 2)) == [
        (start, start + timedelta(days=2)),
        (start + timedelta(days=2), start + timedelta(days=4)),
        (start + timedelta(days=4), end),
    ]
    first = bars(start, start + timedelta(minutes=15))
    second = bars(start + timedelta(minutes=15), start + timedelta(minutes=30))
    result, duplicates, conflicts = merge(first, second, "M15")
    assert (len(result), duplicates, conflicts) == (3, 1, 0)
    revised, _, conflicts = merge(result, bars(start + timedelta(minutes=15), close=3), "M15")
    assert conflicts == 1
    assert revised.iloc[1]["close"] == 3


def test_validation_and_fingerprint(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    frame = bars(start, start + timedelta(minutes=15))
    store = ResearchHistoryStore(tmp_path)
    store.save(frame, "X", "M15")
    assert store.load("X", "M15").equals(normalize(frame, "M15"))
    assert fingerprint(store.load("X", "M15"), "M15") == fingerprint(frame, "M15")
    bad = frame.copy()
    bad.loc[0, "high"] = 0
    with pytest.raises(HistoryError):
        store.save(bad, "X", "M15")
    assert len(store.load("X", "M15")) == 2
    bad = frame.copy()
    bad.loc[0, "tick_volume"] = -1
    with pytest.raises(HistoryError):
        normalize(bad, "M15")


def test_acquisition_resume_and_closure(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    class Provider:
        calls = []
        def tick(self, symbol):
            return type("Tick", (), {"time": start + timedelta(days=3, minutes=10)})()
        def rates_window(self, symbol, timeframe, begin, end):
            self.calls.append((begin, end))
            times = [start + timedelta(days=d) for d in range(4)]
            return bars(*(t for t in times if begin <= t < end))
    provider = Provider()
    store = ResearchHistoryStore(tmp_path)
    first = acquire(provider, store, "X", "D1", start, start + timedelta(days=4),
                    warmup_days=0, chunk_days=2, progress=lambda _: None)
    assert first.count == 3  # day 3 is still forming at broker tick time
    assert first.end_reached is False
    assert store.load("X", "D1")["time"].iloc[-1] == pd.Timestamp(start + timedelta(days=2))
    provider.calls.clear()
    acquire(provider, store, "X", "D1", start, start + timedelta(days=4),
            warmup_days=0, chunk_days=2, progress=lambda _: None)
    assert len(provider.calls) == 1  # first chunk reused; missing tail retried


def test_d1_open_hours_are_preserved(tmp_path):
    start = datetime(2026, 1, 1, 23, tzinfo=UTC)
    frame = bars(start, start + timedelta(days=1), start + timedelta(days=2, hours=1))
    store = ResearchHistoryStore(tmp_path)
    store.save(frame, "X", "D1")
    assert list(store.load("X", "D1")["time"].dt.strftime("%H:%M")) == ["23:00", "23:00", "00:00"]
    assert len(normalize(bars(start, start + timedelta(hours=5)), "H4")) == 2


def test_failed_chunk_preserves_existing_dataset(tmp_path, monkeypatch):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    store = ResearchHistoryStore(tmp_path)
    store.save(bars(start), "X", "D1")
    before = fingerprint(store.load("X", "D1"), "D1")
    class FailingProvider:
        def tick(self, symbol):
            return type("Tick", (), {"time": start + timedelta(days=10)})()
        def rates_window(self, *args):
            raise ProviderError("temporary bridge failure")
    monkeypatch.setattr("src.research.acquisition.time.sleep", lambda _: None)
    with pytest.raises(ProviderError, match="chunk"):
        acquire(FailingProvider(), store, "X", "D1", start, start + timedelta(days=2),
                warmup_days=0, chunk_days=1, progress=lambda _: None)
    assert fingerprint(store.load("X", "D1"), "D1") == before


def test_remote_bounded_window_uses_exclusive_to(monkeypatch):
    provider = RemoteMT5Provider("http://localhost")
    seen = []
    monkeypatch.setattr(provider, "_get", lambda path: (seen.append(path), {"bars": []})[1])
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=14)
    assert provider.rates_window("XAUUSDc", "M15", start, end).empty
    assert f"from={int(start.timestamp())}&to={int(end.timestamp())}" in seen[0]
