"""Synthetic provider for development and testing without a live terminal.

Enabled with PROVIDER=mock in .env. Generates deterministic OHLC data so the
full pipeline (sync, indicators, market state, CLI) can be exercised on any
platform. Never used for real trading decisions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from ..models import AccountInfo, Position, SymbolInfo, Tick
from .closure import latest_closed_bar_open
from .errors import ProviderError
from .history import RATE_COLUMNS, timeframe_delta
from .provider import TradingProvider

logger = logging.getLogger(__name__)

_MOCK_SYMBOLS = [
    ("XAUUSDm", "Gold vs US Dollar", "Metals\\Gold", "USD", "USD", 2, 0.01, 100.0, 0.01, 100.0, 0.01),
    ("XAGUSDm", "Silver vs US Dollar", "Metals\\Silver", "USD", "USD", 3, 0.001, 5000.0, 0.01, 100.0, 0.01),
    ("EURUSDm", "Euro vs US Dollar", "Forex\\Majors", "EUR", "USD", 5, 1e-05, 100000.0, 0.01, 100.0, 0.01),
    ("GBPUSDm", "Pound vs US Dollar", "Forex\\Majors", "GBP", "USD", 5, 1e-05, 100000.0, 0.01, 100.0, 0.01),
    ("USDJPYm", "US Dollar vs Yen", "Forex\\Majors", "USD", "JPY", 3, 0.001, 100000.0, 0.01, 100.0, 0.01),
    ("BTCUSD", "Bitcoin vs US Dollar", "Crypto\\BTC", "BTC", "USD", 2, 0.01, 1.0, 0.001, 10.0, 0.001),
    ("ETHUSD", "Ethereum vs US Dollar", "Crypto\\ETH", "ETH", "USD", 2, 0.01, 1.0, 0.01, 100.0, 0.01),
]


class MockProvider(TradingProvider):
    """Deterministic synthetic data provider."""

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._rng = np.random.default_rng(seed)
        self._connected = False
        self._base_prices = {
            "XAUUSDm": 3700.0, "XAGUSDm": 42.0, "EURUSDm": 1.08, "GBPUSDm": 1.27,
            "USDJPYm": 150.0, "BTCUSD": 62000.0, "ETHUSD": 3100.0,
        }
        self._trends = {
            "XAUUSDm": 0.0004, "XAGUSDm": 0.0002, "EURUSDm": -0.0003,
            "GBPUSDm": 0.0001, "USDJPYm": 0.0002, "BTCUSD": 0.0005, "ETHUSD": -0.0002,
        }

    def connect(self) -> None:
        self._connected = True
        logger.info("Mock provider connected (seed=%d)", self._seed)

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def account_info(self) -> AccountInfo:
        self._require()
        return AccountInfo(
            login=12345678,
            server="Broker-Demo",
            name="Mock Trader",
            currency="USD",
            balance=10000.0,
            equity=9927.40,
            profit=-72.60,
            margin=341.22,
            margin_free=9586.18,
            margin_level=2910.5,
            leverage=500,
            trade_allowed=True,
            open_positions=2,
            floating_drawdown_pct=0.73,
            margin_utilization_pct=3.44,
            free_margin_ratio=28.09,
        )

    def available_symbols(self) -> list[SymbolInfo]:
        self._require()
        return [
            SymbolInfo(
                name=name, description=desc, path=path, currency_base=base,
                currency_profit=profit, digits=digits, point=point,
                contract_size=size, volume_min=vmin, volume_max=vmax,
                volume_step=vstep, trade_mode=0, visible=True, spread=15.0,
            )
            for name, desc, path, base, profit, digits, point, size, vmin, vmax, vstep in _MOCK_SYMBOLS
        ]

    def positions(self) -> list[Position]:
        self._require()
        now = datetime.now(timezone.utc)
        return [
            Position(
                ticket=123456, symbol="XAUUSDm", type="BUY", volume=0.10,
                price_open=3712.42, price_current=3725.80, sl=3690.00, tp=3760.00,
                profit=133.80, swap=-1.20, magic=0, comment="mock",
                time=now - timedelta(hours=5),
            ),
            Position(
                ticket=123457, symbol="USDJPYm", type="SELL", volume=0.20,
                price_open=151.20, price_current=150.40, sl=152.00, tp=149.00,
                profit=-206.40, swap=0.40, magic=0, comment="mock",
                time=now - timedelta(hours=26),
            ),
        ]

    def rates(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        self._require()
        if symbol not in self._base_prices:
            raise ProviderError(f"Mock provider: unknown symbol {symbol}")
        delta = timeframe_delta(timeframe)
        # Closed-candle invariant: the last generated bar is the latest
        # completed bar (never the currently forming one).
        end = latest_closed_bar_open(datetime.now(timezone.utc), timeframe)
        times = pd.date_range(end=end, periods=count, freq=delta, tz="UTC")
        base = self._base_prices[symbol]
        trend = self._trends[symbol]
        steps = self._rng.normal(trend, 0.004, size=count)
        closes = base * np.exp(np.cumsum(steps))
        opens = np.roll(closes, 1)
        opens[0] = closes[0] * (1 - steps[0])
        spread = base * 0.0002
        highs = np.maximum(opens, closes) * (1 + np.abs(self._rng.normal(0, 0.0015, size=count)))
        lows = np.minimum(opens, closes) * (1 - np.abs(self._rng.normal(0, 0.0015, size=count)))
        return pd.DataFrame({
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": self._rng.integers(50, 500, size=count),
            "spread": np.full(count, spread),
            "real_volume": 0,
        })

    def rates_since(self, symbol: str, timeframe: str, since: datetime, count: int) -> pd.DataFrame:
        df = self.rates(symbol, timeframe, count)
        return df[df["time"] >= pd.Timestamp(since)].reset_index(drop=True)

    def tick(self, symbol: str) -> Tick:
        self._require()
        if symbol not in self._base_prices:
            raise ProviderError(f"Mock provider: unknown symbol {symbol}")
        now = datetime.now(timezone.utc)
        last_bar = latest_closed_bar_open(now, "M1")
        price = self._base_prices[symbol]
        return Tick(
            symbol=symbol,
            time=now,
            bid=price * 0.9999,
            ask=price * 1.0001,
            last=price,
            volume=1.0,
            flags=0,
        )

    def _require(self) -> None:
        if not self._connected:
            raise ProviderError("Mock provider is not connected")
