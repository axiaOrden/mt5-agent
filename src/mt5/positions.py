"""Open-position discovery from the MT5 terminal."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..models import Position
from .errors import ProviderError

logger = logging.getLogger(__name__)


def fetch_positions(mt5: Any) -> list[Position]:
    """Retrieve every currently open position (read-only)."""
    raw = mt5.positions_get()
    if raw is None:
        raise ProviderError(f"MT5 positions_get failed: {mt5.last_error()}")
    result = []
    for p in raw:
        result.append(
            Position(
                ticket=p.ticket,
                symbol=p.symbol,
                type="BUY" if p.type == 0 else "SELL",
                volume=p.volume,
                price_open=p.price_open,
                price_current=p.price_current,
                sl=p.sl if p.sl else None,
                tp=p.tp if p.tp else None,
                profit=p.profit,
                swap=p.swap,
                magic=p.magic,
                comment=getattr(p, "comment", "") or "",
                time=pd.Timestamp(p.time, unit="s", tz="UTC").to_pydatetime(),
            )
        )
    return result
