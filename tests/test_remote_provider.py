"""Unit tests for RemoteMT5Provider using a fake local HTTP bridge.

No live MT5 terminal is required. The fake bridge serves canned JSON over
real HTTP so the full request/response path (including timeouts and
malformed payloads) is exercised.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd
import pytest

from src.main import _monitoring_universe
from src.models import SymbolInfo
from src.mt5.errors import ProviderError
from src.mt5.remote import RemoteMT5Provider
from src.mt5.symbols import SymbolResolver

ACCOUNT = {
    "login": 987654,
    "server": "Broker-Live",
    "name": "Real Trader",
    "currency": "USD",
    "balance": 25000.0,
    "equity": 25120.5,
    "profit": 120.5,
    "margin": 500.0,
    "margin_free": 24620.5,
    "margin_level": 5024.1,
    "leverage": 100,
    "trade_allowed": True,
    "open_positions": 1,
}

SYMBOLS = [
    {
        "name": "XAUUSDc",
        "description": "Gold vs US Dollar",
        "path": "Metals\\Gold",
        "currency_base": "USD",
        "currency_profit": "USD",
        "digits": 2,
        "point": 0.01,
        "contract_size": 100.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "trade_mode": 0,
        "visible": True,
        "spread": 15.0,
    },
    {
        "name": "EURUSDc",
        "description": "Euro vs US Dollar",
        "path": "Forex\\Majors",
        "currency_base": "EUR",
        "currency_profit": "USD",
        "digits": 5,
        "point": 1e-05,
        "contract_size": 100000.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "trade_mode": 0,
        "visible": True,
        "spread": 1.0,
    },
]

POSITIONS = [
    {
        "ticket": 555001,
        "symbol": "XAUUSDc",
        "type": "BUY",
        "volume": 0.10,
        "price_open": 3700.0,
        "price_current": 3712.5,
        "sl": 3680.0,
        "tp": 3750.0,
        "profit": 125.0,
        "swap": -0.5,
        "magic": 0,
        "comment": "manual",
        "time": 1700000000,
    }
]

BARS = [
    {
        "time": 1700000000 + i * 900,
        "open": 3700.0 + i,
        "high": 3701.0 + i,
        "low": 3699.0 + i,
        "close": 3700.5 + i,
        "tick_volume": 100,
        "spread": 15,
        "real_volume": 0,
    }
    for i in range(5)
]

TICK = {
    "symbol": "XAUUSDc",
    "time": 1700000000,
    "bid": 3712.4,
    "ask": 3712.6,
    "last": 3712.5,
    "volume": 1.0,
    "flags": 0,
}

HEALTH_OK = {
    "alive": True,
    "initialized": True,
    "connected": True,
    "logged_in": True,
    "terminal": "Z:\\terminal64.exe",
    "account_login": 987654,
    "version": "5.0.6180",
    "error": None,
}


class FakeBridge(BaseHTTPRequestHandler):
    """Canned-response bridge for tests."""

    responses: dict = {}
    delay: float = 0.0
    malformed: bool = False

    def log_message(self, fmt, *args):  # silence test output
        pass

    def do_GET(self):  # noqa: N802
        if self.delay:
            time.sleep(self.delay)
        if self.malformed:
            body = b"not json at all"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        path = self.path.split("?")[0]
        if path.startswith("/rates_range/"):
            from_ts = 0
            for pair in (self.path.split("?")[1].split("&") if "?" in self.path else []):
                key, _, value = pair.partition("=")
                if key == "from":
                    from_ts = int(value)
            payload = {
                "symbol": "XAUUSDc",
                "timeframe": "M15",
                "count": len([b for b in BARS if b["time"] >= from_ts]),
                "bars": [b for b in BARS if b["time"] >= from_ts],
            }
            status = 200
        elif path in self.responses:
            payload = self.responses[path]
            status = 200
        else:
            payload = {"error": f"not found: {path}"}
            status = 404
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def bridge():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBridge)
    FakeBridge.responses = {
        "/health": HEALTH_OK,
        "/account": ACCOUNT,
        "/symbols": {"symbols": SYMBOLS},
        "/positions": {"positions": POSITIONS},
        "/rates/XAUUSDc/M15": {"symbol": "XAUUSDc", "timeframe": "M15", "count": len(BARS), "bars": BARS},
        "/rates_range/XAUUSDc/M15": {"symbol": "XAUUSDc", "timeframe": "M15", "count": len(BARS), "bars": BARS},
        "/tick/XAUUSDc": TICK,
    }
    FakeBridge.delay = 0.0
    FakeBridge.malformed = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _provider(bridge, **kwargs):
    return RemoteMT5Provider(bridge, **kwargs)


def test_connect_ok(bridge):
    provider = _provider(bridge)
    provider.connect()
    assert provider.is_connected()
    provider.disconnect()
    assert not provider.is_connected()


def test_connect_rejects_uninitialized_bridge(bridge):
    FakeBridge.responses["/health"] = {**HEALTH_OK, "initialized": False, "error": "init failed"}
    with pytest.raises(ProviderError, match="not initialized"):
        _provider(bridge).connect()


def test_connect_rejects_not_logged_in(bridge):
    FakeBridge.responses["/health"] = {**HEALTH_OK, "logged_in": False}
    with pytest.raises(ProviderError, match="not logged in"):
        _provider(bridge).connect()


def test_account_conversion(bridge):
    provider = _provider(bridge)
    provider.connect()
    account = provider.account_info()
    assert account.login == 987654
    assert account.server == "Broker-Live"
    assert account.currency == "USD"
    assert account.balance == 25000.0
    assert account.equity == 25120.5
    assert account.profit == 120.5
    assert account.margin == 500.0
    assert account.margin_free == 24620.5
    assert account.margin_level == 5024.1
    assert account.leverage == 100
    assert account.trade_allowed is True
    assert account.open_positions == 1


def test_symbol_retrieval(bridge):
    provider = _provider(bridge)
    provider.connect()
    symbols = provider.available_symbols()
    assert len(symbols) == 2
    gold = symbols[0]
    assert gold.name == "XAUUSDc"  # exact broker name preserved
    assert gold.description == "Gold vs US Dollar"
    assert gold.path == "Metals\\Gold"
    assert gold.currency_base == "USD"
    assert gold.digits == 2
    assert gold.contract_size == 100.0
    assert gold.volume_min == 0.01
    assert gold.visible is True
    assert gold.spread == 15.0
    assert gold.category == "METALS"


def test_position_conversion(bridge):
    provider = _provider(bridge)
    provider.connect()
    positions = provider.positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.ticket == 555001
    assert p.symbol == "XAUUSDc"
    assert p.type == "BUY"
    assert p.volume == 0.10
    assert p.price_open == 3700.0
    assert p.price_current == 3712.5
    assert p.sl == 3680.0
    assert p.tp == 3750.0
    assert p.profit == 125.0
    assert p.swap == -0.5
    assert p.magic == 0
    assert p.comment == "manual"
    assert p.time == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_rates_conversion(bridge):
    provider = _provider(bridge)
    provider.connect()
    df = provider.rates("XAUUSDc", "M15", 5)
    assert len(df) == 5
    assert list(df.columns) == ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    assert df["time"].dt.tz is not None
    assert df["close"].iloc[-1] == 3704.5
    assert df["time"].is_monotonic_increasing


def test_rates_since_filters(bridge):
    provider = _provider(bridge)
    provider.connect()
    since = datetime.fromtimestamp(1700000000 + 2 * 900, tz=timezone.utc)
    df = provider.rates_since("XAUUSDc", "M15", since, 5)
    assert len(df) == 3
    assert df["time"].iloc[0] >= pd.Timestamp(since)


def test_tick_conversion(bridge):
    provider = _provider(bridge)
    provider.connect()
    tick = provider.tick("XAUUSDc")
    assert tick.symbol == "XAUUSDc"
    assert tick.bid == 3712.4
    assert tick.ask == 3712.6
    assert tick.last == 3712.5
    assert tick.volume == 1.0
    assert tick.time == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert tick.spread == pytest.approx(0.2)


def test_bridge_unavailable():
    provider = RemoteMT5Provider("http://127.0.0.1:1", timeout=1.0)
    with pytest.raises(ProviderError, match="unreachable"):
        provider.connect()


def test_malformed_response(bridge):
    FakeBridge.malformed = True
    provider = _provider(bridge)
    with pytest.raises(ProviderError, match="malformed JSON"):
        provider.connect()


def test_http_timeout(bridge):
    FakeBridge.delay = 1.5
    provider = _provider(bridge, timeout=0.2)
    with pytest.raises(ProviderError, match="timeout"):
        provider.connect()


def test_unsupported_timeframe(bridge):
    provider = _provider(bridge)
    provider.connect()
    with pytest.raises(ProviderError, match="Unsupported timeframe"):
        provider.rates("XAUUSDc", "M2", 5)


def test_bridge_http_error_surface(bridge):
    provider = _provider(bridge)
    provider.connect()
    with pytest.raises(ProviderError, match="HTTP 404"):
        provider.rates("NOSUCH", "M15", 5)


def test_ambiguous_broker_symbols():
    # Broker uses XAUUSDc; both XAUUSDc and XAUUSDm exist -> ambiguous, no guess.
    available = [SymbolInfo(name="XAUUSDc"), SymbolInfo(name="XAUUSDm"), SymbolInfo(name="EURUSDc")]
    resolver = SymbolResolver(available)
    result = resolver.resolve(["XAUUSD"])[0]
    assert not result.resolved
    assert result.status == "ambiguous"
    assert set(result.candidates) == {"XAUUSDc", "XAUUSDm"}


def test_unique_broker_suffix_resolution():
    # Only XAUUSDc exists -> conservative unique suffix match.
    available = [SymbolInfo(name="XAUUSDc"), SymbolInfo(name="EURUSDc")]
    resolver = SymbolResolver(available)
    result = resolver.resolve(["XAUUSD"])[0]
    assert result.resolved
    assert result.broker == "XAUUSDc"
    assert result.status == "suffix"


def test_open_position_symbol_inclusion():
    # Position on XAUUSDc must enter the monitoring universe even when the
    # preferred symbol is unresolved.
    from src.mt5.symbols import ResolutionResult

    resolutions = [ResolutionResult("XAUUSD", None, "missing", ())]
    positions = [
        type("P", (), {"symbol": "XAUUSDc"})(),
        type("P", (), {"symbol": "EURUSDc"})(),
    ]
    universe = _monitoring_universe(resolutions, positions)
    assert "XAUUSDc" in universe
    assert "EURUSDc" in universe
