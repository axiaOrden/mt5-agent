"""Unit tests for deterministic account-health classification."""

import pytest

from src.analysis.account_health import AccountHealthAnalyzer
from src.config import AccountRiskConfig
from src.models import AccountInfo

RISK = AccountRiskConfig(
    warning_drawdown_pct=5.0,
    critical_drawdown_pct=10.0,
    warning_margin_level_pct=300.0,
    critical_margin_level_pct=150.0,
    max_positions=10,
)


def _account(**overrides) -> AccountInfo:
    base = dict(
        login=1, server="s", name="", currency="USD", balance=10000.0,
        equity=10000.0, profit=0.0, margin=100.0, margin_free=9900.0,
        margin_level=10000.0, leverage=100, trade_allowed=True, open_positions=0,
    )
    base.update(overrides)
    return AccountInfo(**base)


def test_healthy_account():
    health = AccountHealthAnalyzer(RISK).analyze(_account())
    assert health.state == "HEALTHY"


def test_warning_drawdown():
    health = AccountHealthAnalyzer(RISK).analyze(_account(profit=-600.0))
    assert health.state == "WARNING"
    assert any("drawdown" in r for r in health.reasons)


def test_critical_drawdown():
    health = AccountHealthAnalyzer(RISK).analyze(_account(profit=-1200.0))
    assert health.state == "CRITICAL"


def test_warning_margin_level():
    health = AccountHealthAnalyzer(RISK).analyze(_account(margin_level=250.0))
    assert health.state == "WARNING"


def test_critical_margin_level():
    health = AccountHealthAnalyzer(RISK).analyze(_account(margin_level=120.0))
    assert health.state == "CRITICAL"


def test_max_positions_warning():
    health = AccountHealthAnalyzer(RISK).analyze(_account(open_positions=10))
    assert health.state == "WARNING"
    assert any("positions" in r for r in health.reasons)


def test_trading_disabled_is_critical():
    health = AccountHealthAnalyzer(RISK).analyze(_account(trade_allowed=False))
    assert health.state == "CRITICAL"
    assert any("trading disabled" in r for r in health.reasons)


def test_critical_overrides_warning():
    health = AccountHealthAnalyzer(RISK).analyze(
        _account(profit=-1200.0, margin_level=120.0, open_positions=10)
    )
    assert health.state == "CRITICAL"


def test_positive_floating_profit_no_drawdown():
    health = AccountHealthAnalyzer(RISK).analyze(_account(profit=500.0))
    assert health.state == "HEALTHY"


def test_open_positions_count_parameter_overrides():
    health = AccountHealthAnalyzer(RISK).analyze(_account(), open_positions=12)
    assert health.state == "WARNING"


def test_deterministic():
    analyzer = AccountHealthAnalyzer(RISK)
    account = _account(profit=-600.0, margin_level=250.0)
    assert analyzer.analyze(account) == analyzer.analyze(account)
