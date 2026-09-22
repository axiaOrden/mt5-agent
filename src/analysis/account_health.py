"""Deterministic, configuration-driven account-health classification.

No LLM is involved. Rules are evaluated in priority order; the worst
triggered state wins (CRITICAL > WARNING > HEALTHY).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

from ..config import AccountRiskConfig
from ..models import AccountHealth, AccountInfo

logger = logging.getLogger(__name__)

HEALTHY = "HEALTHY"
WARNING = "WARNING"
CRITICAL = "CRITICAL"


class AccountHealthAnalyzer:
    def __init__(self, risk: AccountRiskConfig) -> None:
        self._risk = risk

    def analyze(self, account: AccountInfo, open_positions: Optional[int] = None) -> AccountHealth:
        """Classify account health from an AccountInfo snapshot."""
        reasons: list[str] = []
        state = HEALTHY

        if not account.trade_allowed:
            state = CRITICAL
            reasons.append("trading disabled on account")

        drawdown = self._floating_drawdown(account)
        if drawdown is not None:
            if drawdown >= self._risk.critical_drawdown_pct:
                state = CRITICAL
                reasons.append(f"drawdown {drawdown:.2f}% >= critical {self._risk.critical_drawdown_pct}%")
            elif drawdown >= self._risk.warning_drawdown_pct:
                state = WARNING
                reasons.append(f"drawdown {drawdown:.2f}% >= warning {self._risk.warning_drawdown_pct}%")

        margin_level = account.margin_level
        if margin_level > 0:
            if margin_level <= self._risk.critical_margin_level_pct:
                state = CRITICAL
                reasons.append(f"margin level {margin_level:.1f}% <= critical {self._risk.critical_margin_level_pct}%")
            elif margin_level <= self._risk.warning_margin_level_pct:
                state = WARNING
                reasons.append(f"margin level {margin_level:.1f}% <= warning {self._risk.warning_margin_level_pct}%")

        count = open_positions if open_positions is not None else account.open_positions
        if count >= self._risk.max_positions and state == HEALTHY:
            state = WARNING
            reasons.append(f"open positions {count} >= max {self._risk.max_positions}")

        if state == HEALTHY:
            reasons.append("all metrics within configured limits")

        logger.info("account health: %s (%s)", state, "; ".join(reasons))
        return AccountHealth(state=state, reasons=tuple(reasons))

    @staticmethod
    def _floating_drawdown(account: AccountInfo) -> Optional[float]:
        """Floating drawdown as % of balance (0 when flat or positive)."""
        if account.balance <= 0:
            return None
        return max(0.0, -account.profit / account.balance * 100.0)


def derive_metrics(account: AccountInfo) -> AccountInfo:
    """Populate derived display metrics (drawdown, margin usage, free ratio)."""
    drawdown = AccountHealthAnalyzer._floating_drawdown(account)
    margin_util = (account.margin / account.equity * 100.0) if account.equity > 0 else None
    free_ratio = (account.margin_free / account.margin) if account.margin > 0 else None
    return replace(
        account,
        floating_drawdown_pct=drawdown,
        margin_utilization_pct=margin_util,
        free_margin_ratio=free_ratio,
    )
