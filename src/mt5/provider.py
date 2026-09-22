"""Trading provider abstraction.

Everything outside this package talks to ``TradingProvider`` and stays
unaware of whether MT5 runs locally or on a remote machine.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import pandas as pd

from ..models import AccountInfo, Position, SymbolInfo, Tick
from .account import fetch_account_info
from .connection import initialize, login, shutdown, verify_account
from .errors import ProviderError
from .history import fetch_rates, fetch_rates_since
from .positions import fetch_positions
from .symbols import fetch_symbols

logger = logging.getLogger(__name__)


class TradingProvider(ABC):
    """Abstract interface to a trading account / market data source."""

    @abstractmethod
    def connect(self) -> None:
        """Establish the connection. Raise ProviderError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection."""

    @abstractmethod
    def is_connected(self) -> bool:
        """True when the provider is connected and usable."""

    @abstractmethod
    def account_info(self) -> AccountInfo:
        """Current account snapshot."""

    @abstractmethod
    def available_symbols(self) -> list[SymbolInfo]:
        """Complete set of symbols available to the connected account."""

    @abstractmethod
    def positions(self) -> list[Position]:
        """Every currently open position."""

    @abstractmethod
    def rates(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """Most recent ``count`` OHLC bars for ``symbol`` on ``timeframe``.

        Returns a DataFrame with columns:
        time (datetime64[ns, UTC]), open, high, low, close,
        tick_volume, spread, real_volume.
        """

    def rates_since(self, symbol: str, timeframe: str, since: datetime, count: int) -> pd.DataFrame:
        """Bars from ``since`` (UTC) to now. Default: fetch recent bars and filter."""
        df = self.rates(symbol, timeframe, count)
        since_ts = pd.Timestamp(since)
        if since_ts.tzinfo is None:
            since_ts = since_ts.tz_localize("UTC")
        return df[df["time"] >= since_ts].reset_index(drop=True)

    def rates_window(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Closed bars whose opens lie in [start, end); deep research only."""
        raise ProviderError(f"bounded history not supported by {type(self).__name__}")

    def tick(self, symbol: str) -> Tick:
        """Latest tick for ``symbol``. Providers without tick support raise ProviderError."""
        raise ProviderError(f"tick not supported by {type(self).__name__}")


class MT5Provider(TradingProvider):
    """TradingProvider backed by the official MetaTrader5 Python package.

    The MetaTrader5 module is imported lazily so the rest of the system can
    be developed, tested and run on platforms where the package is not
    available (e.g. Linux). A future RemoteMT5Provider will expose the same
    interface over the network.
    """

    def __init__(self, terminal_path: Optional[str] = None,
                 login: Optional[int] = None,
                 password: Optional[str] = None,
                 server: Optional[str] = None) -> None:
        self._terminal_path = terminal_path
        self._login = login
        self._password = password
        self._server = server
        self._mt5 = None
        self._connected = False

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:
            raise ProviderError(
                "The MetaTrader5 package is not installed. It is Windows-only "
                "(it wraps the MT5 terminal DLL). On this platform use a remote "
                "provider or run the analysis engine on Windows."
            ) from exc

        self._mt5 = mt5
        initialize(mt5, self._terminal_path)

        if self._login is not None:
            login(mt5, self._login, self._password or "", self._server or "")

        verify_account(mt5)

        self._connected = True
        logger.info("MT5 connected (terminal=%s)", self._terminal_path or "default")

    def disconnect(self) -> None:
        if self._mt5 is not None:
            shutdown(self._mt5)
        self._connected = False
        logger.info("MT5 disconnected")

    def is_connected(self) -> bool:
        return self._connected

    # -- data --------------------------------------------------------------

    def account_info(self) -> AccountInfo:
        self._require_connected()
        return fetch_account_info(self._mt5)

    def available_symbols(self) -> list[SymbolInfo]:
        self._require_connected()
        return fetch_symbols(self._mt5)

    def positions(self) -> list[Position]:
        self._require_connected()
        return fetch_positions(self._mt5)

    def rates(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        self._require_connected()
        return fetch_rates(self._mt5, symbol, timeframe, count)

    def rates_since(self, symbol: str, timeframe: str, since: datetime, count: int) -> pd.DataFrame:
        self._require_connected()
        return fetch_rates_since(self._mt5, symbol, timeframe, since, count)

    def rates_window(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
        self._require_connected()
        from .history import fetch_rates_window
        return fetch_rates_window(self._mt5, symbol, timeframe, start, end)

    def tick(self, symbol: str) -> Tick:
        self._require_connected()
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ProviderError(f"MT5 symbol_info_tick failed for {symbol}: {self._mt5.last_error()}")
        return Tick(
            symbol=symbol,
            time=pd.Timestamp(tick.time, unit="s", tz="UTC").to_pydatetime(),
            bid=float(tick.bid),
            ask=float(tick.ask),
            last=float(tick.last),
            volume=float(tick.volume),
            flags=int(tick.flags),
        )

    # -- helpers -----------------------------------------------------------

    def _require_connected(self) -> None:
        if not self._connected or self._mt5 is None:
            raise ProviderError("MT5 provider is not connected")
