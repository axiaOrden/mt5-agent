"""MT5 terminal lifecycle: initialize, login, shutdown, error reporting."""

from __future__ import annotations

import logging
from typing import Any, Optional

from .errors import ProviderError

logger = logging.getLogger(__name__)


def initialize(mt5: Any, terminal_path: Optional[str] = None) -> None:
    """Initialize the MT5 terminal. Raises ProviderError on failure."""
    if not mt5.initialize(terminal_path or None):
        raise ProviderError(f"MT5 initialization failed: {mt5.last_error()}")
    logger.info("MT5 terminal initialized (path=%s)", terminal_path or "default")


def login(mt5: Any, login: int, password: str, server: str) -> None:
    """Authorize an account. Raises ProviderError on failure."""
    if not mt5.login(login, password=password, server=server):
        raise ProviderError(f"MT5 login failed: {mt5.last_error()}")
    logger.info("MT5 account login authorized (login=%s)", login)


def verify_account(mt5: Any) -> None:
    """Ensure an account is actually available. Raises ProviderError otherwise."""
    if mt5.account_info() is None:
        raise ProviderError(f"MT5 account unavailable: {mt5.last_error()}")


def shutdown(mt5: Any) -> None:
    """Shut the terminal down (idempotent)."""
    try:
        mt5.shutdown()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("MT5 shutdown raised: %s", exc)
    logger.info("MT5 terminal shut down")
