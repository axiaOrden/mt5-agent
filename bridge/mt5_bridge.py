"""Read-only MT5 bridge for Wine-hosted MetaTrader 5.

Runs under Windows Python (Wine) and exposes a minimal HTTP API on
127.0.0.1 so the native Linux application can read account, symbols,
positions, historical rates and ticks without touching the MT5 DLL.

Transport adapter only: no analysis, no trade execution, no order_send.

Endpoints (all GET, read-only):
    /health
    /account
    /symbols
    /positions
    /rates/{symbol}/{timeframe}?count=N          (completed bars only)
    /rates_range/{symbol}/{timeframe}?from=UNIX&count=N  (completed bars only)
    /tick/{symbol}

Configuration via environment:
    MT5_TERMINAL_WINDOWS   terminal path in Windows form, e.g.
                           Z:\\home\\heaxia\\App\\exe\\fx\\mt5\\terminal64.exe
    MT5_BRIDGE_HOST        bind address (default 127.0.0.1, never 0.0.0.0)
    MT5_BRIDGE_PORT        bind port (default 8765)

Stdlib only — no third-party packages required.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mt5-bridge")

TERMINAL = os.environ.get("MT5_TERMINAL_WINDOWS", "")
HOST = os.environ.get("MT5_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("MT5_BRIDGE_PORT", "8765"))

# Same timeframe set as the native history layer.
TIMEFRAMES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769, "MN1": 49153,
}

# Bar durations in seconds, used for closed-candle filtering.
TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN1": 2592000,
}

_mt5: Any = None
_init_error: Optional[str] = None


def _ensure_initialized() -> Any:
    """Import MetaTrader5 and initialize the terminal (idempotent, self-healing)."""
    global _mt5, _init_error
    if _mt5 is not None:
        return _mt5
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        _init_error = f"MetaTrader5 package unavailable: {exc}"
        raise RuntimeError(_init_error)

    if not mt5.initialize(path=TERMINAL or None):
        _init_error = f"MT5 initialization failed: {mt5.last_error()}"
        raise RuntimeError(_init_error)

    _mt5 = mt5
    _init_error = None
    logger.info("MT5 initialized (terminal=%s)", TERMINAL or "default")
    return mt5


def _health() -> dict:
    alive = True
    connected = False
    logged_in = False
    account_login: Optional[int] = None
    error: Optional[str] = _init_error
    try:
        mt5 = _ensure_initialized()
        terminal = mt5.terminal_info()
        connected = terminal is not None and bool(terminal.connected)
        account = mt5.account_info()
        logged_in = account is not None
        if account is not None:
            account_login = account.login
    except Exception as exc:  # noqa: BLE001 - report any failure
        error = str(exc)
    return {
        "alive": alive,
        "initialized": _mt5 is not None,
        "connected": connected,
        "logged_in": logged_in,
        "terminal": TERMINAL,
        "account_login": account_login,
        "version": getattr(_mt5, "__version__", None) if _mt5 is not None else None,
        "error": error,
    }


def _account() -> dict:
    mt5 = _ensure_initialized()
    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"account_info failed: {mt5.last_error()}")
    positions = mt5.positions_get()
    return {
        "login": info.login,
        "server": info.server,
        "name": getattr(info, "name", "") or "",
        "currency": info.currency,
        "balance": info.balance,
        "equity": info.equity,
        "profit": info.profit,
        "margin": info.margin,
        "margin_free": info.margin_free,
        "margin_level": info.margin_level,
        "leverage": info.leverage,
        "trade_allowed": bool(info.trade_allowed),
        "open_positions": len(positions) if positions is not None else 0,
    }


def _symbols() -> list[dict]:
    mt5 = _ensure_initialized()
    names = mt5.symbols_get()
    if names is None:
        raise RuntimeError(f"symbols_get failed: {mt5.last_error()}")
    result = []
    for s in names:
        info = mt5.symbol_info(s.name)
        if info is None:
            logger.warning("symbol_info failed for %s: %s", s.name, mt5.last_error())
            continue
        result.append(
            {
                "name": info.name,
                "description": getattr(info, "description", "") or "",
                "path": getattr(info, "path", "") or "",
                "currency_base": getattr(info, "currency_base", "") or "",
                "currency_profit": getattr(info, "currency_profit", "") or "",
                "digits": info.digits,
                "point": info.point,
                "contract_size": info.trade_contract_size,
                "volume_min": info.volume_min,
                "volume_max": info.volume_max,
                "volume_step": info.volume_step,
                "trade_mode": info.trade_mode,
                "visible": bool(info.visible),
                "spread": float(info.spread) if info.spread else None,
            }
        )
    return result


def _positions() -> list[dict]:
    mt5 = _ensure_initialized()
    raw = mt5.positions_get()
    if raw is None:
        raise RuntimeError(f"positions_get failed: {mt5.last_error()}")
    result = []
    for p in raw:
        result.append(
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl if p.sl else None,
                "tp": p.tp if p.tp else None,
                "profit": p.profit,
                "swap": p.swap,
                "magic": p.magic,
                "comment": getattr(p, "comment", "") or "",
                "time": int(p.time),
            }
        )
    return result


def _rates(symbol: str, timeframe: str, count: int) -> dict:
    """Most recent ``count`` COMPLETED bars.

    Position 1 is the latest completed bar; position 0 is the currently
    forming candle, which must never enter strategy history.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    mt5 = _ensure_initialized()
    raw = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 1, count)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"no historical data for {symbol} {timeframe}: {mt5.last_error()}")
    return _bars_payload(symbol, timeframe, raw)


def _rates_range(symbol: str, timeframe: str, since_ts: int, count: int) -> dict:
    """Bars from ``since_ts`` (unix seconds) up to now, closed candles only.

    Range retrieval can include the currently forming bar; it is explicitly
    filtered out using the latest tick time as broker "now"
    (``bar_open + duration <= tick_time``). If no tick is available, the
    latest completed bar from a positional call is used as the cutoff.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    mt5 = _ensure_initialized()
    from_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc)
    raw = mt5.copy_rates_range(symbol, TIMEFRAMES[timeframe], from_dt, datetime.now(timezone.utc))
    if raw is None or len(raw) == 0:
        return {"symbol": symbol, "timeframe": timeframe, "count": 0, "bars": []}

    duration = TIMEFRAME_SECONDS[timeframe]
    tick = mt5.symbol_info_tick(symbol)
    if tick is not None:
        cutoff = int(tick.time) - duration
    else:
        anchor = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 1, 1)
        if anchor is None or len(anchor) == 0:
            cutoff = None
        else:
            cutoff = int(anchor[0]["time"])
    if cutoff is not None:
        raw = [r for r in raw if int(r["time"]) <= cutoff]
    return _bars_payload(symbol, timeframe, raw)


def _bars_payload(symbol: str, timeframe: str, raw: Any) -> dict:
    bars = [
        {
            "time": int(r["time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
            "spread": int(r["spread"]),
            "real_volume": int(r["real_volume"]),
        }
        for r in raw
    ]
    return {"symbol": symbol, "timeframe": timeframe, "count": len(bars), "bars": bars}


def _tick(symbol: str) -> dict:
    mt5 = _ensure_initialized()
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise KeyError(f"no tick for {symbol}")
    return {
        "symbol": symbol,
        "time": int(tick.time),
        "bid": float(tick.bid),
        "ask": float(tick.ask),
        "last": float(tick.last),
        "volume": float(tick.volume),
        "flags": int(tick.flags),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "MT5Bridge/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/health":
                self._json(200, _health())
            elif path == "/account":
                self._json(200, _account())
            elif path == "/symbols":
                self._json(200, {"symbols": _symbols()})
            elif path == "/positions":
                self._json(200, {"positions": _positions()})
            elif path.startswith("/rates_range/"):
                self._handle_rates_range(parsed)
            elif path.startswith("/rates/"):
                self._handle_rates(parsed)
            elif path.startswith("/tick/"):
                self._handle_tick(path)
            else:
                self._json(404, {"error": f"not found: {path}"})
        except KeyError as exc:
            self._json(404, {"error": str(exc)})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(503, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - never crash the server
            logger.exception("unhandled error on %s", self.path)
            self._json(500, {"error": str(exc)})

    def _handle_rates(self, parsed: Any) -> None:
        parts = parsed.path.split("/")
        if len(parts) != 4 or not parts[2] or not parts[3]:
            self._json(400, {"error": "expected /rates/{symbol}/{timeframe}"})
            return
        symbol, timeframe = parts[2], parts[3]
        count = 1000
        query = parsed.query
        if query:
            for pair in query.split("&"):
                key, _, value = pair.partition("=")
                if key == "count":
                    try:
                        count = int(value)
                    except ValueError:
                        self._json(400, {"error": "count must be an integer"})
                        return
        if count <= 0 or count > 100000:
            self._json(400, {"error": "count out of range"})
            return
        self._json(200, _rates(symbol, timeframe, count))

    def _handle_rates_range(self, parsed: Any) -> None:
        parts = parsed.path.split("/")
        if len(parts) != 4 or not parts[2] or not parts[3]:
            self._json(400, {"error": "expected /rates_range/{symbol}/{timeframe}"})
            return
        symbol, timeframe = parts[2], parts[3]
        since_ts = 0
        count = 1000
        for pair in parsed.query.split("&") if parsed.query else []:
            key, _, value = pair.partition("=")
            if key == "from":
                try:
                    since_ts = int(value)
                except ValueError:
                    self._json(400, {"error": "from must be an integer (unix seconds)"})
                    return
            elif key == "count":
                try:
                    count = int(value)
                except ValueError:
                    self._json(400, {"error": "count must be an integer"})
                    return
        if since_ts < 0 or count <= 0 or count > 100000:
            self._json(400, {"error": "from/count out of range"})
            return
        self._json(200, _rates_range(symbol, timeframe, since_ts, count))

    def _handle_tick(self, path: str) -> None:
        parts = path.split("/")
        if len(parts) != 3 or not parts[2]:
            self._json(400, {"error": "expected /tick/{symbol}"})
            return
        self._json(200, _tick(parts[2]))

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    if HOST != "127.0.0.1" and HOST != "localhost":
        logger.error("refusing to bind on %s: bridge must stay on localhost", HOST)
        return 1
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.info("MT5 bridge listening on http://%s:%d", HOST, PORT)
    logger.info("terminal=%s", TERMINAL or "default")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.server_close()
        if _mt5 is not None:
            try:
                _mt5.shutdown()
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
