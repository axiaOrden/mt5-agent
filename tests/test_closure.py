"""Phase 1.7 tests: closed-candle invariant, cache repair, mock determinism,
read-only guarantees."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.mt5.closure import (
    bar_duration,
    filter_closed_bars,
    is_bar_closed,
    latest_closed_bar_open,
    latest_closed_bar_timestamp,
)
from src.mt5.history import HistoryStore, merge_history
from src.mt5.mock import MockProvider
from src.mt5.remote import RemoteMT5Provider

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(n: int, start: datetime, freq: str = "15min", close_offset: float = 0.0) -> pd.DataFrame:
    times = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i + close_offset for i in range(n)],
            "tick_volume": [100] * n,
            "spread": [1.0] * n,
            "real_volume": [0] * n,
        }
    )


# --------------------------------------------------------------------------
# Closed-candle helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("timeframe,minutes", [("M15", 15), ("H1", 60), ("H4", 240), ("D1", 1440)])
def test_latest_completed_bar_retained_per_timeframe(timeframe, minutes):
    """The latest completed M15/H1/H4/D1 bar is retained; the forming one is dropped."""
    df = _bars(5, T0, freq=f"{minutes}min")
    broker_now = T0 + timedelta(minutes=minutes * 4 + minutes // 2)  # mid-way into the 5th bar
    closed = filter_closed_bars(df, timeframe, broker_now)
    assert len(closed) == 4
    assert closed["time"].iloc[-1] == df["time"].iloc[3]


def test_forming_bar_excluded_from_strategy_history():
    df = _bars(5, T0, freq="60min")  # bars at 00:00..04:00
    broker_now = T0 + timedelta(hours=4, minutes=10)  # 04:00 bar still forming
    closed = filter_closed_bars(df, "H1", broker_now)
    assert len(closed) == 4
    assert closed["time"].iloc[-1] == df["time"].iloc[3]


def test_is_bar_closed_boundary():
    assert is_bar_closed(T0, "M15", T0 + timedelta(minutes=14, seconds=59)) is False
    assert is_bar_closed(T0, "M15", T0 + timedelta(minutes=15)) is True


def test_is_bar_closed_naive_timestamp_treated_as_utc():
    naive = datetime(2024, 1, 1, 0, 0)
    assert is_bar_closed(naive, "M15", T0 + timedelta(minutes=15)) is True


def test_latest_closed_bar_open_grid():
    now = T0 + timedelta(hours=3, minutes=10)
    assert latest_closed_bar_open(now, "H1") == T0 + timedelta(hours=2)
    # 03:10 -> the 03:00 M15 bar closes at 03:15, so the latest closed is 02:45.
    assert latest_closed_bar_open(now, "M15") == T0 + timedelta(hours=2, minutes=45)


def test_latest_closed_bar_timestamp_none_when_all_forming():
    df = _bars(2, T0)
    assert latest_closed_bar_timestamp(df, "H1", T0 + timedelta(minutes=30)) is None


def test_bar_duration_unsupported_raises():
    with pytest.raises(ValueError):
        bar_duration("M2")


# --------------------------------------------------------------------------
# Cache repair: stale forming bars
# --------------------------------------------------------------------------

class _ClosedOnlyProvider:
    """Returns closed bars ending at ``end``; tick time is ``end + duration``."""

    def __init__(self, bars: pd.DataFrame, timeframe: str) -> None:
        self._bars = bars
        self._timeframe = timeframe

    def rates(self, symbol, timeframe, count):
        return self._bars.tail(count).reset_index(drop=True)

    def rates_since(self, symbol, timeframe, since, count):
        return self._bars[self._bars["time"] >= pd.Timestamp(since)].reset_index(drop=True)

    def tick(self, symbol):
        from src.models import Tick

        last = self._bars["time"].iloc[-1]
        return Tick(
            symbol=symbol,
            time=(last + bar_duration(self._timeframe)).to_pydatetime(),
            bid=1.0,
            ask=1.0,
            last=1.0,
            volume=1.0,
        )


def test_sync_repairs_stale_forming_bar(tmp_path):
    """A stale previously-forming bar in the cache is dropped on next sync."""
    store = HistoryStore(tmp_path)
    # Simulate an old Phase 1 cache: closed bars 00:00, 00:15 plus a forming
    # snapshot of the 00:30 bar (stored while it was still forming).
    closed = _bars(2, T0)
    forming = _bars(1, T0 + timedelta(minutes=30))
    stale = merge_history(closed, forming)
    store.save(stale, "XAUUSDm", "M15")

    # Provider now returns only closed bars (up to 00:15); tick at 00:30
    # means the 00:30 bar is still forming.
    provider = _ClosedOnlyProvider(closed, "M15")
    result = store.sync(provider, "XAUUSDm", "M15", 100)
    assert result.bars_after == 2
    loaded = store.load("XAUUSDm", "M15")
    assert loaded["time"].iloc[-1] == T0 + timedelta(minutes=15)


def test_sync_replaces_forming_snapshot_with_final_ohlc(tmp_path):
    """A bar cached while forming is replaced by the broker's final closed OHLC."""
    store = HistoryStore(tmp_path)
    closed_early = _bars(2, T0)
    forming = _bars(1, T0 + timedelta(minutes=30), close_offset=1000.0)  # snapshot close
    store.save(merge_history(closed_early, forming), "XAUUSDm", "M15")

    # Provider now has the 00:30 bar CLOSED with final values (close 100.5+2).
    final = _bars(3, T0)
    provider = _ClosedOnlyProvider(final, "M15")
    result = store.sync(provider, "XAUUSDm", "M15", 100)
    assert result.bars_after == 3
    loaded = store.load("XAUUSDm", "M15")
    assert loaded["time"].iloc[-1] == T0 + timedelta(minutes=30)
    assert loaded["close"].iloc[-1] == pytest.approx(102.5)  # final, not the snapshot


def test_sync_keeps_latest_closed_bar_anchor(tmp_path):
    store = HistoryStore(tmp_path)
    provider = _ClosedOnlyProvider(_bars(5, T0), "M15")
    store.sync(provider, "XAUUSDm", "M15", 100)
    anchor = store.latest_closed_bar_timestamp("XAUUSDm", "M15")
    assert anchor == T0 + timedelta(minutes=60)
    assert store.latest_closed_bar_timestamp("XAUUSDm", "H1") is None


# --------------------------------------------------------------------------
# Mock provider: deterministic and closed-bars-only
# --------------------------------------------------------------------------

def test_mock_provider_deterministic():
    a = MockProvider(seed=42)
    b = MockProvider(seed=42)
    a.connect()
    b.connect()
    df_a = a.rates("XAUUSDm", "M15", 50)
    df_b = b.rates("XAUUSDm", "M15", 50)
    pd.testing.assert_frame_equal(df_a, df_b)


def test_mock_provider_generates_closed_bars_only():
    provider = MockProvider(seed=42)
    provider.connect()
    for tf in ("M15", "H1", "H4", "D1"):
        df = provider.rates("XAUUSDm", tf, 50)
        tick = provider.tick("XAUUSDm")
        closed = filter_closed_bars(df, tf, tick.time)
        assert len(closed) == len(df), f"{tf}: mock emitted a forming bar"


# --------------------------------------------------------------------------
# Read-only guarantees
# --------------------------------------------------------------------------

def test_remote_provider_has_no_trade_methods():
    forbidden = {"order_send", "order_calc_margin", "order_calc_profit", "buy", "sell", "close"}
    for name in forbidden:
        assert not hasattr(RemoteMT5Provider, name), f"RemoteMT5Provider must not expose {name}"


def test_bridge_source_has_no_trade_execution():
    source = open("bridge/mt5_bridge.py", encoding="utf-8").read()
    assert "order_send(" not in source
    assert "do_POST" not in source
    assert "positions_get" in source  # read-only position discovery only
