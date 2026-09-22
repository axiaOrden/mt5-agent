"""Position domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Position:
    """A single open MT5 position (read-only view)."""

    ticket: int
    symbol: str
    type: str  # BUY | SELL
    volume: float
    price_open: float
    price_current: float
    sl: Optional[float]
    tp: Optional[float]
    profit: float
    swap: float
    magic: int
    comment: str
    time: datetime

    @property
    def type_label(self) -> str:
        return self.type
