"""Account domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AccountInfo:
    """Snapshot of the trading account as reported by the provider."""

    login: int
    server: str
    name: str
    currency: str
    balance: float
    equity: float
    profit: float
    margin: float
    margin_free: float
    margin_level: float
    leverage: int
    trade_allowed: bool
    open_positions: int = 0

    # Derived metrics (computed by AccountHealthAnalyzer, kept here for display).
    floating_drawdown_pct: Optional[float] = None
    margin_utilization_pct: Optional[float] = None
    free_margin_ratio: Optional[float] = None

    @property
    def leverage_label(self) -> str:
        return f"1:{self.leverage}" if self.leverage else "n/a"


@dataclass(frozen=True)
class AccountHealth:
    """Deterministic account-health classification."""

    state: str  # HEALTHY | WARNING | CRITICAL
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        return self.state
