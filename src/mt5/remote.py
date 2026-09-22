"""RemoteMT5Provider — TradingProvider backed by the read-only Wine MT5 bridge.

The native Linux application talks to a small HTTP bridge running under
Windows Python (Wine) which wraps the official MetaTrader5 package. This
provider is a transport adapter only: it converts bridge JSON into the
existing domain models and never duplicates analysis logic.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from ..models import AccountInfo, Position, SymbolInfo, Tick
from .errors import ProviderError
from .history import RATE_COLUMNS, SUPPORTED_TIMEFRAMES
from .provider import TradingProvider

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class RemoteMT5Provider(TradingProvider):
    """Read-only HTTP client for the Wine MT5 bridge."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._connected = False

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        health = self._get("/health")
        if not health.get("alive"):
            raise ProviderError(f"bridge not alive: {health.get('error') or 'unknown'}")
        if not health.get("initialized"):
            raise ProviderError(f"bridge MT5 not initialized: {health.get('error') or 'unknown'}")
        if not health.get("connected"):
            raise ProviderError("bridge terminal not connected")
        if not health.get("logged_in"):
            raise ProviderError("bridge terminal not logged in")
        self._connected = True
        logger.info("RemoteMT5Provider connected to %s", self._base_url)

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # -- data --------------------------------------------------------------

    def account_info(self) -> AccountInfo:
        data = self._get("/account")
        return AccountInfo(
            login=int(data["login"]),
            server=str(data.get("server", "")),
            name=str(data.get("name", "")),
            currency=str(data.get("currency", "")),
            balance=float(data["balance"]),
            equity=float(data["equity"]),
            profit=float(data["profit"]),
            margin=float(data["margin"]),
            margin_free=float(data["margin_free"]),
            margin_level=float(data["margin_level"]),
            leverage=int(data["leverage"]),
            trade_allowed=bool(data.get("trade_allowed", True)),
            open_positions=int(data.get("open_positions", 0)),
        )

    def available_symbols(self) -> list[SymbolInfo]:
        data = self._get("/symbols")
        result = []
        for s in data.get("symbols", []):
            result.append(
                SymbolInfo(
                    name=str(s["name"]),
                    description=str(s.get("description", "")),
                    path=str(s.get("path", "")),
                    currency_base=str(s.get("currency_base", "")),
                    currency_profit=str(s.get("currency_profit", "")),
                    digits=int(s.get("digits", 0)),
                    point=float(s.get("point", 0.0)),
                    contract_size=float(s.get("contract_size", 0.0)),
                    volume_min=float(s.get("volume_min", 0.0)),
                    volume_max=float(s.get("volume_max", 0.0)),
                    volume_step=float(s.get("volume_step", 0.0)),
                    trade_mode=int(s.get("trade_mode", 0)),
                    visible=bool(s.get("visible", True)),
                    spread=float(s["spread"]) if s.get("spread") is not None else None,
                )
            )
        return result

    def positions(self) -> list[Position]:
        data = self._get("/positions")
        result = []
        for p in data.get("positions", []):
            result.append(
                Position(
                    ticket=int(p["ticket"]),
                    symbol=str(p["symbol"]),
                    type=str(p.get("type", "BUY")),
                    volume=float(p["volume"]),
                    price_open=float(p["price_open"]),
                    price_current=float(p["price_current"]),
                    sl=float(p["sl"]) if p.get("sl") is not None else None,
                    tp=float(p["tp"]) if p.get("tp") is not None else None,
                    profit=float(p["profit"]),
                    swap=float(p.get("swap", 0.0)),
                    magic=int(p.get("magic", 0)),
                    comment=str(p.get("comment", "")),
                    time=pd.Timestamp(int(p["time"]), unit="s", tz="UTC").to_pydatetime(),
                )
            )
        return result

    def rates(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        self._validate_timeframe(timeframe)
        path = f"/rates/{urllib.parse.quote(symbol)}/{timeframe}?count={int(count)}"
        data = self._get(path)
        return self._bars_to_frame(data)

    def rates_since(self, symbol: str, timeframe: str, since: datetime, count: int) -> pd.DataFrame:
        """Bars from ``since`` (UTC) to now, completed bars only.

        Uses the bridge's range endpoint, which explicitly filters out the
        currently forming bar using broker tick time.
        """
        self._validate_timeframe(timeframe)
        since_ts = int(pd.Timestamp(since).timestamp())
        path = (
            f"/rates_range/{urllib.parse.quote(symbol)}/{timeframe}"
            f"?from={since_ts}&count={int(count)}"
        )
        data = self._get(path)
        return self._bars_to_frame(data)

    def tick(self, symbol: str) -> Tick:
        path = f"/tick/{urllib.parse.quote(symbol)}"
        data = self._get(path)
        return Tick(
            symbol=str(data["symbol"]),
            time=pd.Timestamp(int(data["time"]), unit="s", tz="UTC").to_pydatetime(),
            bid=float(data["bid"]),
            ask=float(data["ask"]),
            last=float(data["last"]),
            volume=float(data.get("volume", 0.0)),
            flags=int(data.get("flags", 0)),
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _bars_to_frame(data: dict) -> pd.DataFrame:
        bars = data.get("bars", [])
        if not bars:
            return pd.DataFrame(columns=RATE_COLUMNS)
        df = pd.DataFrame(bars)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df[RATE_COLUMNS]

    def _get(self, path: str) -> dict:
        url = self._base_url + path
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:  # noqa: S310 - localhost bridge
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _read_error(exc)
            raise ProviderError(f"bridge HTTP {exc.code} for {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"bridge unreachable at {self._base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderError(f"bridge timeout for {path}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"bridge returned malformed JSON for {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError(f"bridge returned unexpected payload for {path}")
        return payload

    @staticmethod
    def _validate_timeframe(timeframe: str) -> None:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise ProviderError(f"Unsupported timeframe: {timeframe}")


def _read_error(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
        payload = json.loads(body)
        return str(payload.get("error", body))
    except Exception:  # noqa: BLE001
        return str(exc)
