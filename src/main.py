"""MT5 Trading Analysis Agent — Phase 1 CLI.

Read-only. This phase never places, modifies or closes trades.

Commands:
    status            Full startup workflow + account/positions/market report
    symbols [filter]  Available broker symbols (optional search filter)
    sync              Synchronize historical data for the monitoring universe
    scan              Multi-timeframe market-state table
    analyze SYMBOL    Detailed Ichimoku analysis for one logical symbol
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .analysis import AccountHealthAnalyzer, MarketStateAnalyzer, derive_metrics
from .config import Config, load_config, setup_logging
from .models import AccountHealth, AccountInfo, MarketState, Position, SymbolInfo
from .mt5 import MT5Provider, ProviderError, RemoteMT5Provider, ResolutionResult, SymbolResolver, TradingProvider
from .mt5.history import HistoryError, HistoryStore
from .mt5.mock import MockProvider

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    config: Config
    provider: TradingProvider
    account: AccountInfo
    health: AccountHealth
    available: list[SymbolInfo]
    resolutions: list[ResolutionResult]
    positions: list[Position]
    monitoring: list[str] = field(default_factory=list)
    histories: dict[str, dict[str, pd.DataFrame]] = field(default_factory=dict)
    market_states: dict[str, MarketState] = field(default_factory=dict)


def build_provider(config: Config) -> TradingProvider:
    if config.provider == "mock":
        return MockProvider()
    if config.provider == "mt5":
        return MT5Provider(
            terminal_path=config.mt5_terminal_path,
            login=config.mt5_login,
            password=config.mt5_password,
            server=config.mt5_server,
        )
    if config.provider == "remote":
        return RemoteMT5Provider(config.mt5_remote_url, timeout=config.mt5_remote_timeout)
    raise ProviderError(f"Unknown provider: {config.provider!r} (use 'mt5', 'mock' or 'remote')")


def startup(config: Config, provider: TradingProvider, sync_data: bool = True) -> AppContext:
    """Run the startup workflow: connect, account, health, symbols, positions,
    monitoring universe, then (optionally) history sync + market states."""
    provider.connect()
    try:
        account = derive_metrics(provider.account_info())
        health = AccountHealthAnalyzer(config.risk).analyze(account)

        available = provider.available_symbols()
        resolver = SymbolResolver(available)
        resolutions = resolver.resolve(list(config.preferred_symbols), config.symbol_mappings)

        positions = provider.positions()

        monitoring = _monitoring_universe(resolutions, positions)
        ctx = AppContext(
            config=config,
            provider=provider,
            account=account,
            health=health,
            available=available,
            resolutions=resolutions,
            positions=positions,
            monitoring=monitoring,
        )

        if sync_data:
            ctx.histories = sync_all(config, provider, monitoring)
            ctx.market_states = analyze_all(ctx.histories, monitoring)
        return ctx
    except Exception:
        provider.disconnect()
        raise


def _monitoring_universe(resolutions: list[ResolutionResult], positions: list[Position]) -> list[str]:
    """Preferred resolved symbols + every open-position symbol, deduplicated."""
    universe: list[str] = []
    seen: set[str] = set()
    for r in resolutions:
        if r.resolved and r.broker not in seen:
            seen.add(r.broker)
            universe.append(r.broker)
    for p in positions:
        if p.symbol not in seen:
            seen.add(p.symbol)
            universe.append(p.symbol)
    return universe


def sync_all(config: Config, provider: TradingProvider, symbols: list[str]) -> dict[str, dict[str, pd.DataFrame]]:
    store = HistoryStore(config.history_dir)
    histories: dict[str, dict[str, pd.DataFrame]] = {}
    for symbol in symbols:
        histories[symbol] = {}
        for tf in config.timeframes:
            try:
                store.sync(provider, symbol, tf, config.history_bars)
                histories[symbol][tf] = store.load(symbol, tf)
            except (ProviderError, HistoryError) as exc:
                logger.error("history sync failed for %s %s: %s", symbol, tf, exc)
    return histories


def analyze_all(histories: dict[str, dict[str, pd.DataFrame]], symbols: list[str]) -> dict[str, MarketState]:
    analyzer = MarketStateAnalyzer()
    states: dict[str, MarketState] = {}
    for symbol in symbols:
        if symbol in histories:
            states[symbol] = analyzer.analyze_multi(histories[symbol], symbol)
    return states


# --------------------------------------------------------------------------
# Display helpers
# --------------------------------------------------------------------------

def _line(char: str = "─", width: int = 40) -> str:
    return char * width


def _fmt_float(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def print_account(account: AccountInfo, health: AccountHealth) -> None:
    print("ACCOUNT")
    print(_line("─"))
    print(f"{'Login':<18}{account.login}")
    print(f"{'Server':<18}{account.server}")
    print(f"{'Name':<18}{account.name or 'n/a'}")
    print(f"{'Currency':<18}{account.currency}")
    print(f"{'Leverage':<18}{account.leverage_label}")
    print()
    print(f"{'Balance':<18}{_fmt_float(account.balance)}")
    print(f"{'Equity':<18}{_fmt_float(account.equity)}")
    print(f"{'Floating':<18}{_fmt_float(account.profit)}")
    print()
    print(f"{'Margin':<18}{_fmt_float(account.margin)}")
    print(f"{'Free Margin':<18}{_fmt_float(account.margin_free)}")
    print(f"{'Margin Level':<18}{_fmt_float(account.margin_level, 1)}%")
    print()
    print(f"{'Drawdown':<18}{_fmt_float(account.floating_drawdown_pct)}%")
    print(f"{'Margin Usage':<18}{_fmt_float(account.margin_utilization_pct)}%")
    print(f"{'Free Margin Ratio':<18}{_fmt_float(account.free_margin_ratio)}")
    print()
    print(f"{'Open Positions':<18}{account.open_positions}")
    print(f"{'Trading Enabled':<18}{'YES' if account.trade_allowed else 'NO'}")
    print()
    print(f"{'Status':<18}{health.state}")
    for reason in health.reasons:
        print(f"{'':<18}· {reason}")
    print()


def print_symbols(available: list[SymbolInfo], search: Optional[str] = None) -> None:
    query = search.upper() if search else None
    filtered = [s for s in available if query is None or query in s.name.upper() or query in s.description.upper()]
    by_category: dict[str, list[SymbolInfo]] = {}
    for s in filtered:
        by_category.setdefault(s.category, []).append(s)

    print("AVAILABLE SYMBOLS")
    print("═" * 40)
    for category in sorted(by_category):
        print(category)
        for s in sorted(by_category[category], key=lambda x: x.name):
            print(s.name)
        print()
    print(f"Total: {len(filtered)} symbols" + (f" (filter: {search})" if search else ""))
    print()


def print_resolutions(resolutions: list[ResolutionResult]) -> None:
    print("SYMBOL RESOLUTION")
    print(_line("─"))
    for r in resolutions:
        if r.resolved:
            print(f"{r.logical:<14} ->  {r.broker:<14} ({r.status})")
        else:
            detail = ", ".join(r.candidates) if r.candidates else "no match"
            print(f"{r.logical:<14} ->  UNRESOLVED ({r.status}: {detail})")
    print()


def print_positions(positions: list[Position]) -> None:
    print("OPEN POSITIONS")
    print("═" * 40)
    if not positions:
        print("(none)")
        print()
        return
    for p in positions:
        print(f"#{p.ticket}")
        print(f"{p.symbol} {p.type} {p.volume:.2f}")
        print()
        print(f"{'Entry':<12}{_fmt_float(p.price_open)}")
        print(f"{'Current':<12}{_fmt_float(p.price_current)}")
        print(f"{'P/L':<12}{_fmt_float(p.profit)}")
        print(f"{'Swap':<12}{_fmt_float(p.swap)}")
        print()
        print(f"{'SL':<12}{_fmt_float(p.sl)}")
        print(f"{'TP':<12}{_fmt_float(p.tp)}")
        print(f"{'Magic':<12}{p.magic}")
        print(f"{'Comment':<12}{p.comment or ''}")
        print(f"{'Opened':<12}{p.time:%Y-%m-%d %H:%M} UTC")
        print()
    print()


def print_market_table(states: dict[str, MarketState], timeframes: tuple[str, ...]) -> None:
    print("MARKET STATE")
    print("═" * 40)
    if not states:
        print("(no market states available)")
        print()
        return
    headers = ["Symbol"] + list(timeframes)
    widths = [max(len(h), *(len(s) for s in states)) for h in headers]
    widths[0] = max(widths[0], *(len(sym) for sym in states))
    for i, tf in enumerate(timeframes):
        widths[i + 1] = max(
            widths[i + 1],
            *(len(states[s].state_for(tf).direction) if states[s].state_for(tf) else 0 for s in states),
        )
    row = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(row)
    print("  ".join("─" * w for w in widths))
    for symbol in sorted(states):
        cells = [symbol.ljust(widths[0])]
        for tf in timeframes:
            st = states[symbol].state_for(tf)
            cells.append((st.direction if st else "n/a").ljust(widths[timeframes.index(tf) + 1]))
        print("  ".join(cells))
    print()


def print_analysis(symbol: str, resolved: str, states: dict[str, MarketState], timeframes: tuple[str, ...]) -> None:
    print(f"Requested: {symbol}")
    print(f"Resolved:  {resolved}")
    print()
    for tf in timeframes:
        st = states.get(resolved, MarketState(resolved)).state_for(tf)
        print(f"{resolved} {tf}")
        print(_line("─"))
        if st is None:
            print("(no data)")
            print()
            continue
        if st.candle_time is not None:
            print(f"{'Candle':<16}{st.candle_time:%Y-%m-%d %H:%M} UTC")
        print(f"{'Closed':<16}{'YES' if st.candle_closed else 'NO'}")
        print()
        print(f"{'Price/Kumo':<16}{st.price_vs_kumo}")
        print(f"{'TK':<16}{st.tenkan_vs_kijun}")
        print(f"{'Projected Kumo':<16}{st.projected_kumo}")
        chikou = st.chikou + (" (obstructed)" if st.chikou_obstructed else "")
        print(f"{'Chikou':<16}{chikou}")
        print(f"{'Kijun':<16}{st.kijun_slope}")
        if st.kumo_thickness_atr is not None:
            print(f"{'Kumo thickness':<16}{st.kumo_thickness_atr:.2f} ATR")
        print()
        print(f"{'Direction':<16}{st.direction}")
        print(f"{'Condition':<16}{st.condition}")
        print(f"{'Score':<16}{st.score:+d} (diagnostic)")
        print()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_status(config: Config) -> int:
    provider = build_provider(config)
    ctx = startup(config, provider, sync_data=True)
    try:
        print("MT5 CONNECTION")
        print(_line("─"))
        print(f"{'Provider':<18}{config.provider}")
        print(f"{'Connected':<18}{'YES' if provider.is_connected() else 'NO'}")
        print()
        print_account(ctx.account, ctx.health)
        print_resolutions(ctx.resolutions)
        print_positions(ctx.positions)
        print("MONITORING UNIVERSE")
        print(_line("─"))
        for s in ctx.monitoring:
            print(s)
        print()
        print_market_table(ctx.market_states, config.timeframes)
    finally:
        provider.disconnect()
    return 0


def cmd_symbols(config: Config, search: Optional[str]) -> int:
    provider = build_provider(config)
    provider.connect()
    try:
        available = provider.available_symbols()
        print_symbols(available, search)
    finally:
        provider.disconnect()
    return 0


def cmd_sync(config: Config) -> int:
    provider = build_provider(config)
    provider.connect()
    try:
        account = provider.account_info()
        available = provider.available_symbols()
        resolutions = SymbolResolver(available).resolve(list(config.preferred_symbols), config.symbol_mappings)
        positions = provider.positions()
        monitoring = _monitoring_universe(resolutions, positions)

        print("HISTORY SYNC")
        print("═" * 40)
        print(f"Account: {account.login} ({account.server})")
        print(f"Monitoring universe: {', '.join(monitoring)}")
        print()

        store = HistoryStore(config.history_dir)
        for symbol in monitoring:
            for tf in config.timeframes:
                try:
                    result = store.sync(provider, symbol, tf, config.history_bars)
                    print(f"{symbol:<12}{tf:<5}{result.bars_before:>6} -> {result.bars:>6} bars (+{result.added})")
                except (ProviderError, HistoryError) as exc:
                    print(f"{symbol:<12}{tf:<5}FAILED: {exc}")
        print()
    finally:
        provider.disconnect()
    return 0


def cmd_scan(config: Config) -> int:
    provider = build_provider(config)
    ctx = startup(config, provider, sync_data=True)
    try:
        print_market_table(ctx.market_states, config.timeframes)
    finally:
        provider.disconnect()
    return 0


def cmd_analyze(config: Config, logical: str) -> int:
    provider = build_provider(config)
    provider.connect()
    try:
        available = provider.available_symbols()
        resolutions = SymbolResolver(available).resolve([logical], config.symbol_mappings)
        resolution = resolutions[0]
        if not resolution.resolved:
            detail = ", ".join(resolution.candidates) if resolution.candidates else "no match"
            print(f"Requested: {logical}")
            print(f"Resolved:  UNRESOLVED ({resolution.status}: {detail})")
            print("Add an explicit mapping in config/symbols.yaml to disambiguate.")
            return 1

        store = HistoryStore(config.history_dir)
        histories: dict[str, pd.DataFrame] = {}
        for tf in config.timeframes:
            try:
                store.sync(provider, resolution.broker, tf, config.history_bars)
                histories[tf] = store.load(resolution.broker, tf)
            except (ProviderError, HistoryError) as exc:
                logger.error("history sync failed for %s %s: %s", resolution.broker, tf, exc)

        # Enforce the closed-candle invariant at analysis time: drop any bar
        # not yet completed at broker time (latest tick).
        broker_now = None
        try:
            broker_now = provider.tick(resolution.broker).time
        except ProviderError:
            logger.warning("tick unavailable for %s; relying on sync-time closure filter", resolution.broker)

        analyzer = MarketStateAnalyzer()
        states = {
            resolution.broker: analyzer.analyze_multi(histories, resolution.broker, broker_now=broker_now)
        }
        print_analysis(logical, resolution.broker, states, config.timeframes)
    finally:
        provider.disconnect()
    return 0


def cmd_latest(config: Config) -> int:
    """Print the latest closed bar timestamp per symbol × timeframe.

    This is the anchor a future event-driven scheduler will poll: when the
    broker's latest closed bar timestamp advances past these values, a new
    sync + analysis is due.
    """
    provider = build_provider(config)
    provider.connect()
    try:
        account = provider.account_info()
        available = provider.available_symbols()
        resolutions = SymbolResolver(available).resolve(list(config.preferred_symbols), config.symbol_mappings)
        positions = provider.positions()
        monitoring = _monitoring_universe(resolutions, positions)

        store = HistoryStore(config.history_dir)
        print("LATEST CLOSED BARS")
        print("═" * 40)
        print(f"Account: {account.login} ({account.server})")
        print()
        for symbol in monitoring:
            for tf in config.timeframes:
                ts = store.latest_closed_bar_timestamp(symbol, tf)
                if ts is None:
                    print(f"{symbol:<12}{tf:<5}no cached history")
                else:
                    print(f"{symbol:<12}{tf:<5}{ts:%Y-%m-%d %H:%M} UTC")
        print()
    finally:
        provider.disconnect()
    return 0


def cmd_history_clear(config: Config, yes: bool) -> int:
    """Delete locally cached history. Requires explicit --yes; never silent."""
    store = HistoryStore(config.history_dir)
    if not store.base_dir.exists():
        print("No history directory found; nothing to clear.")
        return 0
    files = sorted(store.base_dir.rglob("*.parquet"))
    if not files:
        print("No cached history files found; nothing to clear.")
        return 0
    print("HISTORY CLEAR")
    print("═" * 40)
    print(f"Directory: {store.base_dir}")
    print(f"Files to delete: {len(files)}")
    for f in files:
        print(f"  {f.relative_to(store.base_dir)}")
    print()
    if not yes:
        print("Refusing to delete without confirmation. Re-run with --yes to proceed.")
        return 1
    for f in files:
        f.unlink()
    print(f"Deleted {len(files)} cached history file(s).")
    return 0


# --------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mt5-agent",
        description="MT5 Trading Analysis Agent (Phase 1, read-only)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="full startup workflow and report")
    p_symbols = sub.add_parser("symbols", help="list available broker symbols")
    p_symbols.add_argument("filter", nargs="?", default=None, help="optional search filter")
    sub.add_parser("sync", help="synchronize historical data")
    sub.add_parser("scan", help="multi-timeframe market-state table")
    sub.add_parser("latest", help="latest closed bar timestamp per symbol × timeframe")
    p_analyze = sub.add_parser("analyze", help="detailed analysis of one symbol")
    p_analyze.add_argument("symbol", help="logical symbol, e.g. XAUUSD")
    p_clear = sub.add_parser("history-clear", help="delete cached history (requires --yes)")
    p_clear.add_argument("--yes", action="store_true", help="confirm deletion")

    args = parser.parse_args(argv)

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    setup_logging(config)

    try:
        if args.command == "status":
            return cmd_status(config)
        if args.command == "symbols":
            return cmd_symbols(config, args.filter)
        if args.command == "sync":
            return cmd_sync(config)
        if args.command == "scan":
            return cmd_scan(config)
        if args.command == "latest":
            return cmd_latest(config)
        if args.command == "analyze":
            return cmd_analyze(config, args.symbol)
        if args.command == "history-clear":
            return cmd_history_clear(config, args.yes)
    except ProviderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
