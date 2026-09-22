"""Account retrieval from the MT5 terminal."""

from __future__ import annotations

import logging
from typing import Any

from ..models import AccountInfo
from .errors import ProviderError

logger = logging.getLogger(__name__)


def fetch_account_info(mt5: Any) -> AccountInfo:
    """Read the current account snapshot from the MT5 module."""
    info = mt5.account_info()
    if info is None:
        raise ProviderError(f"MT5 account_info failed: {mt5.last_error()}")
    return AccountInfo(
        login=info.login,
        server=info.server,
        name=getattr(info, "name", "") or "",
        currency=info.currency,
        balance=info.balance,
        equity=info.equity,
        profit=info.profit,
        margin=info.margin,
        margin_free=info.margin_free,
        margin_level=info.margin_level,
        leverage=info.leverage,
        trade_allowed=bool(info.trade_allowed),
    )
