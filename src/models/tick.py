"""Tick domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Tick:
    """Latest market tick for a symbol (read-only)."""

    symbol: str
    time: datetime
    bid: float
    ask: float
    last: float
    volume: float
    flags: int = 0

    @property
    def spread(self) -> float:
        return self.ask - self.bid
