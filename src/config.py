"""Configuration loading: .env, symbols.yaml, risk.yaml, logging setup."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env parser (no external dependency). Never logs values."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return data


@dataclass(frozen=True)
class AccountRiskConfig:
    warning_drawdown_pct: float = 5.0
    critical_drawdown_pct: float = 10.0
    warning_margin_level_pct: float = 300.0
    critical_margin_level_pct: float = 150.0
    max_positions: int = 10


@dataclass(frozen=True)
class Config:
    provider: str = "mt5"
    mt5_terminal_path: Optional[str] = None
    mt5_login: Optional[int] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None

    # Remote bridge (PROVIDER=remote)
    mt5_remote_url: str = "http://127.0.0.1:8765"
    mt5_remote_timeout: float = 30.0

    # Wine environment (used by scripts/start-mt5-bridge.sh)
    wine_binary: str = "/usr/bin/wine"
    wine_prefix: str = "/home/heaxia/.wine"
    wine_python: str = ""
    mt5_terminal_linux: str = ""
    mt5_terminal_windows: str = ""
    mt5_bridge_host: str = "127.0.0.1"
    mt5_bridge_port: int = 8765

    preferred_symbols: tuple[str, ...] = ()
    symbol_mappings: dict[str, str] = field(default_factory=dict)
    timeframes: tuple[str, ...] = ("M15", "H1", "H4", "D1")
    history_bars: int = 1000

    risk: AccountRiskConfig = field(default_factory=AccountRiskConfig)

    data_dir: Path = PROJECT_ROOT / "data"
    log_dir: Path = PROJECT_ROOT / "logs"
    log_level: str = "INFO"

    @property
    def history_dir(self) -> Path:
        return self.data_dir / "history"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def load_config(env_path: Optional[Path] = None, config_dir: Optional[Path] = None) -> Config:
    """Load configuration from .env, config/symbols.yaml and config/risk.yaml."""
    env_path = env_path or PROJECT_ROOT / ".env"
    config_dir = config_dir or PROJECT_ROOT / "config"

    _load_dotenv(env_path)

    symbols_cfg = _load_yaml(config_dir / "symbols.yaml")
    risk_cfg = _load_yaml(config_dir / "risk.yaml")

    symbols_section = symbols_cfg.get("symbols", {}) or {}
    account_cfg = risk_cfg.get("account", {})
    risk = AccountRiskConfig(
        warning_drawdown_pct=float(account_cfg.get("warning_drawdown_pct", 5.0)),
        critical_drawdown_pct=float(account_cfg.get("critical_drawdown_pct", 10.0)),
        warning_margin_level_pct=float(account_cfg.get("warning_margin_level_pct", 300.0)),
        critical_margin_level_pct=float(account_cfg.get("critical_margin_level_pct", 150.0)),
        max_positions=int(account_cfg.get("max_positions", 10)),
    )

    data_dir = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
    log_dir = Path(os.environ.get("LOG_DIR", PROJECT_ROOT / "logs"))

    return Config(
        provider=os.environ.get("PROVIDER", "mt5").strip().lower(),
        mt5_terminal_path=os.environ.get("MT5_TERMINAL_PATH") or None,
        mt5_login=_env_int("MT5_LOGIN"),
        mt5_password=os.environ.get("MT5_PASSWORD") or None,
        mt5_server=os.environ.get("MT5_SERVER") or None,
        mt5_remote_url=os.environ.get("MT5_REMOTE_URL", "http://127.0.0.1:8765"),
        mt5_remote_timeout=float(os.environ.get("MT5_REMOTE_TIMEOUT", "30.0")),
        wine_binary=os.environ.get("WINE_BINARY", "/usr/bin/wine"),
        wine_prefix=os.environ.get("WINE_PREFIX", "/home/heaxia/.wine"),
        wine_python=os.environ.get("WINE_PYTHON", ""),
        mt5_terminal_linux=os.environ.get("MT5_TERMINAL_LINUX", ""),
        mt5_terminal_windows=os.environ.get("MT5_TERMINAL_WINDOWS", ""),
        mt5_bridge_host=os.environ.get("MT5_BRIDGE_HOST", "127.0.0.1"),
        mt5_bridge_port=int(os.environ.get("MT5_BRIDGE_PORT", "8765")),
        preferred_symbols=tuple(symbols_section.get("preferred", [])),
        symbol_mappings=dict(symbols_section.get("mappings", {}) or {}),
        timeframes=tuple(symbols_cfg.get("timeframes", ["M15", "H1", "H4", "D1"])),
        history_bars=int(symbols_cfg.get("history", {}).get("bars", 1000)),
        risk=risk,
        data_dir=data_dir,
        log_dir=log_dir,
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )


def _env_int(name: str) -> Optional[int]:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def setup_logging(config: Config) -> None:
    """Configure rotating file + console logging. Never logs credentials."""
    config.log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.log_level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        config.log_dir / "agent.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
