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
import hashlib
import json
import logging
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .analysis import AccountHealthAnalyzer, MarketStateAnalyzer, derive_metrics
from .context import SUPPORTED_CONTEXT_TIMEFRAMES, context_as_of
from .config import Config, load_config, setup_logging
from .models import AccountHealth, AccountInfo, MarketState, Position, SymbolInfo
from .mt5 import MT5Provider, ProviderError, RemoteMT5Provider, ResolutionResult, SymbolResolver, TradingProvider
from .mt5.history import HistoryError, HistoryStore
from .mt5.mock import MockProvider
from .mt5.closure import bar_duration, filter_closed_bars
from .signals import replay_cloudgazer
from .signals.vwap_events import broker_session_anchors
from .research import DEFAULT_HORIZONS, export_parquet, replay_history, summarize
from .research.acquisition import ResearchHistoryStore, acquire, validate_replay_coverage, utc_date, TIMEFRAMES
from .research.vcz_history import replay_native_vcz, replay_native_vcz_encounters, vcz_summary
from .research.vcz_encounters import DEFAULT_ENCOUNTER_HORIZONS, export_vcz_encounters
from .research.analysis import (DEFAULT_HORIZONS as ANALYSIS_HORIZONS, REPORTS,
                                available_horizons, cohort_statistics, dimensions,
                                filter_events, load_replay, overview, report_groups,
                                resolve_fields, segment_events)

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


def _fmt_ratio(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.2f}x"


def _fmt_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.3f}%"


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


def cmd_signals(config: Config, logical: str, timeframe: str, last: int) -> int:
    """Inspect closed broker candles and replay raw events plus Pine state."""
    provider = build_provider(config)
    provider.connect()
    try:
        resolution = SymbolResolver(provider.available_symbols()).resolve([logical], config.symbol_mappings)[0]
        if not resolution.resolved:
            print(f"Unresolved symbol: {logical}", file=sys.stderr)
            return 1
        symbol = resolution.broker
        # Fail closed when the broker tick cannot establish candle closure.
        broker_now = provider.tick(symbol).time
        store = HistoryStore(config.history_dir)
        store.sync(provider, symbol, timeframe, config.history_bars)
        bars = filter_closed_bars(store.load(symbol, timeframe), timeframe, broker_now)
        if bars is None or bars.empty:
            print(f"No broker-verified closed candles for {symbol} {timeframe}", file=sys.stderr)
            return 1
        # Pine resets ta.vwap(hlc3) on timeframe.change("1D"). Use broker D1
        # timestamps as that boundary; closed history is extended through the
        # current intraday session without consuming forming-candle prices.
        if timeframe == "D1":
            daily = bars
        else:
            store.sync(provider, symbol, "D1", config.history_bars)
            daily = filter_closed_bars(store.load(symbol, "D1"), "D1", broker_now)
        daily_opens = broker_session_anchors(daily, pd.Timestamp(bars["time"].iloc[-1]))
        if daily_opens.empty:
            print(f"No broker D1 session boundaries for {symbol}", file=sys.stderr)
            return 1
        transitions = replay_cloudgazer(bars, symbol, timeframe, broker_now=broker_now, daily_opens=daily_opens)
        selected = [t for t in transitions if t.raw_events or t.label][-last:]
        latest = bars.iloc[-1]
        market = MarketStateAnalyzer().analyze(bars, symbol, timeframe, broker_now=broker_now)
        print(f"{symbol} {timeframe} | latest closed {pd.Timestamp(latest['time']):%Y-%m-%d %H:%M} UTC | Closed YES")
        print(f"Market State: {market.direction}/{market.condition} (display only)")
        print("VWAP: Cloudgazer chart-timeframe hlc3 × MT5 tick_volume; reset at broker D1 opens")
        print("Candle UTC          Raw events                                      Winner                Previous New   Label")
        for t in selected:
            raw = ",".join(e.event_type.value for e in t.raw_events)
            winner = t.winning_event.event_type.value if t.winning_event else "-"
            print(f"{t.bar_open_time:%Y-%m-%d %H:%M}  {raw:<47} {winner:<21} {t.previous_state.value:<8} {t.new_state.value:<5} {t.label or '-'}")
            if t.suppressed_events:
                print("  Suppressed: " + ", ".join(e.event_type.value for e in t.suppressed_events))
        if not selected:
            print("(no recent events)")
        return 0
    finally:
        provider.disconnect()


def cmd_context(config: Config, logical: str, event_timeframe: str, window: int) -> int:
    """Display deterministic multi-timeframe facts from verified closed bars."""
    provider = build_provider(config)
    provider.connect()
    try:
        resolution = SymbolResolver(provider.available_symbols()).resolve([logical], config.symbol_mappings)[0]
        if not resolution.resolved:
            print(f"Unresolved symbol: {logical}", file=sys.stderr)
            return 1
        symbol = resolution.broker
        broker_now = provider.tick(symbol).time
        store = HistoryStore(config.history_dir)
        histories: dict[str, pd.DataFrame] = {}
        start = SUPPORTED_CONTEXT_TIMEFRAMES.index(event_timeframe)
        for timeframe in SUPPORTED_CONTEXT_TIMEFRAMES[start:]:
            store.sync(provider, symbol, timeframe, config.history_bars)
            histories[timeframe] = filter_closed_bars(
                store.load(symbol, timeframe), timeframe, broker_now
            )

        context = context_as_of(
            histories, symbol, event_timeframe, broker_now, stability_window=window
        )
        print(symbol)
        print(f"Context at {context.evaluated_at:%Y-%m-%d %H:%M} UTC from verified closed broker candles")
        print()
        print(f"{'TIMEFRAME':<11}{'ROLE':<17}{'STRUCTURE':<27}{'CLOUDGAZER':<13}{'STRUCTURAL':<13}{'CG ALIGNMENT'}")
        for item in context.timeframe_contexts:
            structure = (f"{item.market_direction}/{item.market_condition}"
                         if item.market_direction else "UNAVAILABLE")
            cg_state = item.cloudgazer_state.value if item.cloudgazer_state else "UNAVAILABLE"
            print(f"{item.timeframe:<11}{item.role.value:<17}{structure:<27}{cg_state:<13}"
                  f"{item.structural_alignment.value:<13}{item.cloudgazer_alignment.value}")

        print()
        print(f"Latest {event_timeframe} state event")
        print(_line("─"))
        transition = context.cloudgazer_transition
        if transition and transition.winning_event:
            print(f"{'Candle':<18}{transition.bar_open_time:%Y-%m-%d %H:%M} UTC")
            print(f"{'Event':<18}{transition.winning_event.event_type.value}")
            print(f"{'Direction':<18}{context.event_direction.value if context.event_direction else 'UNAVAILABLE'}")
            print(f"{'Transition':<18}{transition.previous_state.value} -> {transition.new_state.value}")
            print(f"{'Label':<18}{transition.label or 'NONE'}")
            print(f"{'Bars ago':<18}{context.event_age_bars}")
            if transition.suppressed_events:
                print(f"{'Suppressed':<18}{', '.join(e.event_type.value for e in transition.suppressed_events)}")
        else:
            print("(no state-changing event in available history)")

        print()
        print("PVSRA activity on event candle")
        print(_line("─"))
        pvsra = context.event_pvsra
        if pvsra is None:
            print("(unavailable)")
        else:
            print(f"{'Classification':<22}{pvsra.classification.value}")
            print(f"{'Candle direction':<22}{pvsra.candle_direction.value}")
            print(f"{'Volume source':<22}{pvsra.volume_source.value}")
            print(f"{'Volume ratio':<22}{_fmt_ratio(pvsra.volume_ratio)}")
            print(f"{'Spread ratio':<22}{_fmt_ratio(pvsra.spread_ratio)}")
            print(f"{'VWAP displacement':<22}{_fmt_ratio(pvsra.vwap_displacement_ratio)}")

        print()
        print("Recent Cloudgazer state activity")
        print(_line("─"))
        for item in context.timeframe_contexts:
            print(f"{item.timeframe:<18}{item.recent_state_changes} changes / "
                  f"{item.observed_bars} closed bars")
        print()
        return 0
    finally:
        provider.disconnect()


def cmd_replay(
    config: Config,
    logical: str,
    event_timeframe: str,
    horizons: tuple[int, ...],
    window: int,
    bars_requested: int,
    output: Optional[str],
    research_history: bool = False,
    research_from: Optional[str] = None,
    research_to: Optional[str] = None,
) -> int:
    """Build a historical event research dataset from closed broker bars."""
    provider = build_provider(config)
    provider.connect()
    try:
        resolution = SymbolResolver(provider.available_symbols()).resolve([logical], config.symbol_mappings)[0]
        if not resolution.resolved:
            print(f"Unresolved symbol: {logical}", file=sys.stderr)
            return 1
        symbol = resolution.broker
        broker_now = provider.tick(symbol).time
        start_date = utc_date(research_from) if research_history and research_from else None
        end_date = utc_date(research_to) if research_history and research_to else None
        store = (ResearchHistoryStore(config.data_dir / "research" / "history") if research_history
                 else HistoryStore(config.history_dir))
        histories: dict[str, pd.DataFrame] = {}
        start = SUPPORTED_CONTEXT_TIMEFRAMES.index(event_timeframe)
        for timeframe in SUPPORTED_CONTEXT_TIMEFRAMES[start:]:
            if timeframe == event_timeframe:
                requested = bars_requested
            else:
                covered_seconds = bars_requested * bar_duration(event_timeframe).total_seconds()
                requested = max(
                    100,
                    int(covered_seconds / bar_duration(timeframe).total_seconds()) + 100,
                )
            if not research_history:
                store.sync(provider, symbol, timeframe, requested)
            histories[timeframe] = filter_closed_bars(
                store.load(symbol, timeframe), timeframe, broker_now
            )
        if research_history:
            validate_replay_coverage(histories, symbol, start_date, end_date)
        result = replay_history(
            histories, symbol, event_timeframe,
            horizons=horizons, stability_window=window,
            report_from=start_date, report_to=end_date,
        )
        target = (Path(output) if output else
                  config.data_dir / "research" / f"{symbol}_{event_timeframe}_events.parquet")
        export_parquet(result, target)
        stats = summarize(result.events, result.horizons)
        print(f"{symbol} {event_timeframe} HISTORICAL REPLAY")
        print(_line("─"))
        if result.period_start and result.period_end:
            print(f"{'Period':<20}{result.period_start:%Y-%m-%d %H:%M} -> {result.period_end:%Y-%m-%d %H:%M} UTC")
        print(f"{'Closed candles':<20}{result.closed_candles}")
        print(f"{'State events':<20}{len(result.events)}")
        for label in ("BUY", "SELL", "WB", "WS", "NONE"):
            count = sum((event.label or "NONE") == label for event in result.events)
            print(f"{label:<20}{count}")
        if result.missing_d1_coverage:
            print("D1 coverage         INCOMPLETE — early VWAP/PVSRA context may be unavailable")
        print()
        print("Forward research")
        print(_line("─"))
        print(f"{'HORIZON':<10}{'N':<8}{'MEAN DIR':<14}{'MED DIR':<14}{'MED MFE':<14}{'MED MAE'}")
        rows = stats[0].horizons if stats else ()
        for item in rows:
            print(f"{item.horizon:<10}{item.sample_count:<8}{_fmt_pct(item.mean_directional_return):<14}"
                  f"{_fmt_pct(item.median_directional_return):<14}{_fmt_pct(item.median_mfe):<14}"
                  f"{_fmt_pct(item.median_mae)}")
        print()
        print("PVSRA event counts")
        print(_line("─"))
        for group in summarize(result.events, result.horizons, group_by="pvsra_classification"):
            print(f"{group.group:<20}{group.event_count}")
        print()
        print(f"Research dataset: {target}")
        return 0
    finally:
        provider.disconnect()


def cmd_research_sync(config: Config, logical: str, from_date: str, to_date: str,
                      warmup_days: int, chunk_days: int, force_refresh: bool) -> int:
    start, end = utc_date(from_date), utc_date(to_date)
    if end <= start or warmup_days < 0 or chunk_days < 1:
        raise ValueError("research range and chunk days must be positive; warmup days nonnegative")
    provider = build_provider(config)
    provider.connect()
    try:
        resolution = SymbolResolver(provider.available_symbols()).resolve([logical], config.symbol_mappings)[0]
        if not resolution.resolved:
            raise ProviderError(f"Unresolved symbol: {logical}")
        symbol = resolution.broker
        store = ResearchHistoryStore(config.data_dir / "research" / "history")
        reports = []
        print(f"{symbol} RESEARCH HISTORY")
        print(f"Requested [from, to): {start.isoformat()} -> {end.isoformat()}")
        print(f"Warmup: {warmup_days} calendar days; chunk: {chunk_days} days")
        for timeframe in TIMEFRAMES:
            report = acquire(provider, store, symbol, timeframe, start, end,
                             warmup_days=warmup_days, chunk_days=chunk_days,
                             force_refresh=force_refresh)
            reports.append(report)
            print(f"{symbol} {timeframe}: {report.count:,} candles, {report.earliest} -> {report.latest}")
            print(f"  requested start reached: {report.requested_start_reached}; "
                  f"warmup start reached: {report.start_reached}; end reached: {report.end_reached}; "
                  f"continuously usable: {report.continuously_usable}; "
                  f"gaps: {report.discontinuities} (largest {report.largest_gap}); "
                  f"duplicates: {report.duplicates}; revisions: {report.conflicts}; empty chunks: {report.empty_chunks}")
            print(f"  primed year windows: {report.primed_windows}; empty priming windows: "
                  f"{report.empty_prime_windows}; suspicious interior gaps: {len(report.suspicious_interior_gaps)}; "
                  f"unresolved empty chunks: {len(report.unresolved_empty_chunks)}")
            for hole in report.suspicious_interior_gaps[:3]:
                print(f"  SUSPICIOUS GAP: {hole[0]} -> {hole[1]} ({hole[2]})")
            for gap in report.notable_gaps:
                print(f"  gap: {gap[0]} -> {gap[1]} ({gap[2]})")
            if report.d1_open_utc:
                print(f"  D1 open UTC: {report.d1_open_utc}")
            print(f"  SHA256: {report.fingerprint}")
        metadata = {
            "symbol": logical, "broker_symbol": symbol, "requested_from": start.isoformat(),
            "requested_to_exclusive": end.isoformat(), "warmup_days": warmup_days,
            "chunk_days": chunk_days, "acquired_at": datetime.now(timezone.utc).isoformat(),
            "timeframes": [asdict(report) for report in reports],
        }
        path = store.base_dir / symbol / "latest_acquisition.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(metadata, indent=2) + "\n")
        temp.replace(path)
        print(f"Research metadata: {path}")
        return 0
    finally:
        provider.disconnect()


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
    p_signals = sub.add_parser("signals", help="inspect closed-candle raw events and Cloudgazer replay")
    p_signals.add_argument("symbol")
    p_signals.add_argument("--timeframe", choices=("M15", "H1", "H4", "D1"), default="M15")
    p_signals.add_argument("--last", type=int, default=20, help="number of recent event candles")
    p_context = sub.add_parser("context", help="multi-timeframe signal context")
    p_context.add_argument("symbol")
    p_context.add_argument("--timeframe", choices=SUPPORTED_CONTEXT_TIMEFRAMES, default="M15")
    p_context.add_argument("--window", type=int, default=20,
                           help="closed bars used for state stability")
    p_replay = sub.add_parser("replay", help="historical Cloudgazer event research")
    p_replay.add_argument("symbol")
    p_replay.add_argument("--timeframe", choices=SUPPORTED_CONTEXT_TIMEFRAMES, default="M15")
    p_replay.add_argument("--horizons", default=",".join(map(str, DEFAULT_HORIZONS)),
                          help="comma-separated forward bar horizons")
    p_replay.add_argument("--window", type=int, default=20,
                          help="event-time Cloudgazer activity window")
    p_replay.add_argument("--bars", type=int, default=1000,
                          help="explicit research history depth for event timeframe")
    p_replay.add_argument("--output", default=None, help="research Parquet output path")
    p_replay.add_argument("--research-history", action="store_true", help="use separately acquired deep research history")
    p_replay.add_argument("--from", dest="research_from", help="inclusive UTC research date (with --research-history)")
    p_replay.add_argument("--to", dest="research_to", help="exclusive UTC research date (with --research-history)")
    p_research = sub.add_parser("research-sync", help="acquire bounded deep broker history")
    p_research.add_argument("symbol")
    p_research.add_argument("--from", dest="from_date", required=True, help="inclusive UTC date YYYY-MM-DD")
    p_research.add_argument("--to", dest="to_date", required=True, help="exclusive UTC date YYYY-MM-DD")
    p_research.add_argument("--warmup-days", type=int, default=180)
    p_research.add_argument("--chunk-days", type=int, default=14)
    p_research.add_argument("--force-refresh", action="store_true")
    p_vcz = sub.add_parser("vcz", help="offline VCZ price memory from saved native research history")
    p_vcz.add_argument("symbol", help="exact stored broker symbol, e.g. XAUUSDc")
    p_vcz.add_argument("--timeframe", choices=TIMEFRAMES, required=True)
    p_vcz.add_argument("--research-history", action="store_true", required=True,
                       help="read saved research candles without contacting MT5")
    p_vcz.add_argument("--history-dir", default="data/research/history")
    p_vcz.add_argument("--max-zones", type=int, help="optional Pine box-array limit per side (default: full research history)")
    p_vcz.add_argument("--sample", type=int, default=5, help="number of recent surviving zones to print")
    p_enc = sub.add_parser("vcz-encounters", help="offline native-timeframe VCZ encounter observations")
    p_enc.add_argument("symbol", help="exact stored broker symbol")
    p_enc.add_argument("--timeframe", choices=TIMEFRAMES, required=True)
    p_enc.add_argument("--research-history", action="store_true", required=True)
    p_enc.add_argument("--history-dir", default="data/research/history")
    p_enc.add_argument("--from", dest="research_from", help="inclusive UTC encounter date")
    p_enc.add_argument("--to", dest="research_to", help="exclusive UTC encounter date")
    p_enc.add_argument("--horizons", default=",".join(map(str, DEFAULT_ENCOUNTER_HORIZONS)))
    p_enc.add_argument("--output", help="Parquet output path")
    p_cohort = sub.add_parser("research-analyze", help="offline descriptive analysis of replay Parquet")
    p_cohort.add_argument("path", help="Phase 1.9 events Parquet")
    p_cohort.add_argument("--group-by", help="comma-separated persisted categorical fields; direction aliases label")
    p_cohort.add_argument("--where", action="append", default=[], metavar="FIELD=VALUE", help="repeatable AND filter")
    p_cohort.add_argument("--report", choices=REPORTS, default="overview")
    p_cohort.add_argument("--segment-by", choices=("year", "quarter", "month"))
    p_cohort.add_argument("--horizons", help="comma-separated saved outcome horizons (default: 1,4,8,16,32 if present)")
    p_cohort.add_argument("--min-samples", type=int, default=1, help="display only cohorts with at least N events")
    p_cohort.add_argument("--output", help="write cohort rows to CSV or Parquet")
    p_cohort.add_argument("--list-fields", action="store_true", help="list grouping/filter fields in this artifact")
    p_clear = sub.add_parser("history-clear", help="delete cached history (requires --yes)")
    p_clear.add_argument("--yes", action="store_true", help="confirm deletion")

    args = parser.parse_args(argv)

    if args.command == "vcz-encounters":
        try:
            horizons = tuple(int(part.strip()) for part in args.horizons.split(","))
            if not horizons or any(h < 1 for h in horizons) or len(set(horizons)) != len(horizons):
                raise ValueError("--horizons must contain unique positive integers")
            start = utc_date(args.research_from) if args.research_from else None
            end = utc_date(args.research_to) if args.research_to else None
            if start and end and end <= start:
                raise ValueError("--to must follow --from")
            store = ResearchHistoryStore(Path(args.history_dir))
            bars = store.load(args.symbol, args.timeframe)
            daily = store.load(args.symbol, "D1")
            if bars.empty or daily.empty:
                raise ValueError(f"Saved {args.symbol} {args.timeframe}/D1 research history is required")
            replay = replay_native_vcz_encounters(bars, daily, symbol=args.symbol,
                                                   timeframe=args.timeframe, horizons=horizons)
            encounters = tuple(e for e in replay.encounters
                               if (start is None or e.candle_open_time >= start) and
                               (end is None or e.candle_open_time < end))
            replay = replace(replay, encounters=encounters)
            output = Path(args.output) if args.output else Path("data/research/vcz") / f"{args.symbol}_{args.timeframe}_encounters.parquet"
            export_vcz_encounters(replay, output)
            print(f"candles_processed: {replay.candles_processed}")
            print(f"zones_created: {replay.zones_created}")
            print(f"encounters: {len(encounters)}")
            print(f"unique_zones_encountered: {len({e.zone_id for e in encounters})}")
            print(f"output: {output}")
            return 0
        except (OSError, ValueError, HistoryError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.command == "vcz":
        try:
            if args.sample < 0:
                raise ValueError("--sample must be nonnegative")
            store = ResearchHistoryStore(Path(args.history_dir))
            bars = store.load(args.symbol, args.timeframe)
            daily = store.load(args.symbol, "D1")
            if bars.empty or daily.empty:
                raise ValueError(f"Saved {args.symbol} {args.timeframe}/D1 research history is required")
            replay = replay_native_vcz(bars, daily, symbol=args.symbol,
                                       timeframe=args.timeframe, max_zones=args.max_zones)
            for key, value in vcz_summary(replay).items():
                print(f"{key}: {value}")
            if args.sample:
                print("Recent surviving zones (chronological sample):")
                selected = replay.surviving_zones[-args.sample:]
                for zone in selected:
                    age = replay.candles_processed - 1 - zone.created_bar_index
                    print(f"{zone.side.value:<5} {zone.source_bar_open_time.isoformat()} "
                          f"{zone.pvsra_classification.value}/{zone.pvsra_candle_direction.value} "
                          f"original=[{zone.original_bottom:g}, {zone.original_top:g}] "
                          f"remaining=[{zone.current_bottom:g}, {zone.current_top:g}] "
                          f"fraction={zone.remaining_fraction} age_bars={age}")
            return 0
        except (OSError, ValueError, HistoryError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Analysis is deliberately independent of configuration, MT5, and Wine.
    if args.command == "research-analyze":
        try:
            frame = load_replay(args.path)
            if args.list_fields:
                print("Available dimensions (direction is an alias for label):")
                print("\n".join(dimensions(frame)))
                return 0
            horizons = available_horizons(frame)
            if args.horizons:
                try:
                    requested = tuple(int(part.strip()) for part in args.horizons.split(","))
                except ValueError as exc:
                    raise ValueError("--horizons must be comma-separated positive integers") from exc
                if not requested or any(h < 1 for h in requested) or len(set(requested)) != len(requested):
                    raise ValueError("--horizons must contain unique positive integers")
                horizons = requested
            else:
                horizons = tuple(h for h in ANALYSIS_HORIZONS if h in horizons) or horizons
            frame = filter_events(frame, args.where)
            frame = segment_events(frame, args.segment_by)
            if args.group_by:
                groups = [("custom", resolve_fields(frame, args.group_by))]
            else:
                groups = report_groups(frame, args.report)
            tables = []
            if args.report == "overview" and not args.group_by:
                print(overview(frame, horizons))
            for name, fields in groups:
                if args.segment_by:
                    fields = ("period", *fields)
                table = cohort_statistics(frame, fields, horizons, args.min_samples)
                table.insert(0, "report", name)
                tables.append(table)
                print(f"\n{name}: {len(table):,} cohort/horizon rows")
                if not table.empty:
                    print(table.to_string(index=False, float_format=lambda x: f"{x:.6g}"))
            if args.output:
                output = Path(args.output)
                if output.suffix.lower() not in (".csv", ".parquet"):
                    raise ValueError("--output must end in .csv or .parquet")
                output.parent.mkdir(parents=True, exist_ok=True)
                combined = pd.concat(tables, ignore_index=True)
                if output.suffix.lower() == ".csv":
                    combined.to_csv(output, index=False)
                else:
                    combined.to_parquet(output, index=False)
                metadata = {
                    "source_dataset": str(Path(args.path).resolve()),
                    "source_sha256": hashlib.sha256(Path(args.path).read_bytes()).hexdigest(),
                    "report": "custom" if args.group_by else args.report,
                    "grouping_dimensions": {name: list(("period", *fields) if args.segment_by else fields)
                                            for name, fields in groups},
                    "filters": args.where,
                    "segment_by": args.segment_by,
                    "horizons": list(horizons),
                    "min_samples": args.min_samples,
                }
                output.with_name(output.name + ".meta.json").write_text(
                    json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                print(f"Saved {len(combined):,} rows to {output}")
            return 0
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

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
        if args.command == "signals":
            if args.last < 1:
                parser.error("--last must be positive")
            return cmd_signals(config, args.symbol, args.timeframe, args.last)
        if args.command == "context":
            if args.window < 1:
                parser.error("--window must be positive")
            return cmd_context(config, args.symbol, args.timeframe, args.window)
        if args.command == "replay":
            if args.window < 1 or args.bars < 1:
                parser.error("--window and --bars must be positive")
            try:
                horizons = tuple(int(value.strip()) for value in args.horizons.split(",") if value.strip())
            except ValueError:
                parser.error("--horizons must be comma-separated positive integers")
            if not horizons or any(value < 1 for value in horizons):
                parser.error("--horizons must contain positive integers")
            return cmd_replay(
                config, args.symbol, args.timeframe, horizons,
                args.window, args.bars, args.output,
                args.research_history, args.research_from, args.research_to,
            )
        if args.command == "research-sync":
            return cmd_research_sync(config, args.symbol, args.from_date, args.to_date,
                                     args.warmup_days, args.chunk_days, args.force_refresh)
        if args.command == "history-clear":
            return cmd_history_clear(config, args.yes)
    except (ProviderError, HistoryError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
