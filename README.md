# MT5 Trading Analysis Agent — Phase 1.7

Read-only analysis foundation for a MetaTrader 5 account: connection and
account health, dynamic broker symbol discovery, preferred-symbol resolution,
open-position discovery, historical data synchronization, multi-timeframe
Ichimoku calculation and deterministic market-state analysis.

For the current division of observation, research, VCZ price memory, and
execution responsibilities, see [observation architecture](docs/observation-architecture.md).
The independent, offline VCZ V1 price-memory replay is described in
[VCZ V1](docs/vcz-v1.md).

Phase 1.5 replaced mock market/account input with **real MT5 data** through a
read-only HTTP bridge running under Wine. Phase 1.7 enforces the
**closed-candle invariant** (strategy analysis never uses a forming candle),
separates the **current Kumo** from the **projected Kumo**, reworks the
**Chikou** interpretation into a directional confirmation, and replaces the
single trend label with an explicit **direction + condition** classification.

> **Safety boundary: this program is READ-ONLY.**
> It does NOT place trades, modify positions, modify SL/TP, or close
> positions. It may read existing SL/TP values but never changes them.
> Trade execution is intentionally deferred to a later phase.

## Requirements

- Native Linux (CachyOS) Python 3.11+ for the analysis application
- Wine with a Windows Python 3.12 and the `MetaTrader5` package for the bridge
- A running MetaTrader 5 terminal under Wine

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit
```

## Architecture

The application is split into two environments:

```text
Native CachyOS / Linux
    |
    |  mt5-agent
    |  analysis
    |  indicators
    |  risk
    |  history
    |  CLI
    |
    | HTTP localhost
    v
Wine Windows Python
    |
    | MetaTrader5 Python package
    v
MetaTrader 5 terminal
    |
    v
Broker
```

The native application never touches the MT5 DLL. `RemoteMT5Provider`
(`src/mt5/remote.py`) implements the same `TradingProvider` interface as
`MockProvider` and `MT5Provider`, so the analysis layer cannot tell where the
data came from. The bridge (`bridge/mt5_bridge.py`) is a transport adapter
only — it contains no analysis logic and no trade-execution endpoints.

## Configuration

`.env` — provider selection and credentials (never committed):

```ini
PROVIDER=remote            # remote | mock | mt5

MT5_REMOTE_URL=http://127.0.0.1:8765

WINE_BINARY=/usr/bin/wine
WINE_PREFIX=/home/heaxia/.wine
WINE_PYTHON=/home/heaxia/.wine/drive_c/users/heaxia/AppData/Local/Programs/Python/Python312/python.exe

MT5_TERMINAL_LINUX=/home/heaxia/App/exe/fx/mt5/terminal64.exe
MT5_TERMINAL_WINDOWS=Z:\home\heaxia\App\exe\fx\mt5\terminal64.exe

MT5_BRIDGE_HOST=127.0.0.1
MT5_BRIDGE_PORT=8765
LOG_LEVEL=INFO
```

`config/symbols.yaml` — preferred logical symbols, explicit mappings,
timeframes, history depth:

```yaml
symbols:
  preferred: [XAUUSD, XAGUSD, EURUSD, BTCUSD]
  mappings:              # explicit logical -> broker, overrides auto-matching
    XAUUSD: XAUUSDc
timeframes: [M15, H1, H4, D1]
history:
  bars: 1000
```

`config/risk.yaml` — deterministic account-health thresholds:

```yaml
account:
  warning_drawdown_pct: 5
  critical_drawdown_pct: 10
  warning_margin_level_pct: 300
  critical_margin_level_pct: 150
  max_positions: 10
```

## Starting and stopping the bridge

```bash
./scripts/start-mt5-bridge.sh    # reads .env, sets WINEPREFIX, launches bridge
./scripts/check-mt5-bridge.sh    # GET /health, pretty-printed
./scripts/stop-mt5-bridge.sh     # stops the bridge (pid in logs/bridge.pid)
```

The bridge binds to `127.0.0.1` only (it refuses to start on any other
address). Logs go to `logs/bridge.log`.

Bridge endpoints (all GET, read-only):

```text
GET /health
GET /account
GET /symbols
GET /positions
GET /rates/{symbol}/{timeframe}?count=N          (completed bars only)
GET /rates_range/{symbol}/{timeframe}?from=UNIX&count=N  (completed bars only)
GET /tick/{symbol}
```

Timeframes are validated against a whitelist (M1…MN1); arbitrary input is
never passed into MT5. No credentials are exposed by `/health`.

## Closed-candle invariant (Phase 1.7)

Strategy analysis never uses a forming candle:

* `/rates` retrieves from MT5 **position 1** (the latest completed bar);
  position 0 (the forming candle) is never requested.
* `/rates_range` and the direct `copy_rates_range` path explicitly filter
  out any bar that has not completed, using the latest **tick time** as
  broker "now": a bar opening at `t` on a timeframe of duration `d` is
  closed iff `t + d <= broker_now`. The developer machine's local timezone
  is never consulted, and no assumption is made about which wall-clock hour
  a timeframe closes at.
* `HistoryStore.sync` drops any bar not yet closed at broker time **after**
  merging. This both keeps the forming candle out of strategy history and
  repairs stale previously-forming snapshots left in the cache by older
  versions (a bar cached while forming is replaced by the broker's final
  closed OHLC once it completes).
* `analyze` additionally re-filters the loaded history with the live tick
  before analysis, and reports the analyzed candle's opening timestamp and
  `Closed: YES`.

### One-time migration after upgrading to Phase 1.7

The Parquet cache may contain forming bars written by earlier phases. The
sync-time closed-bar filter repairs them automatically, but the cleanest
migration is:

```bash
.venv/bin/python -m src.main history-clear --yes   # removes old cache
.venv/bin/python -m src.main sync                  # rebuild closed-only history
```

`history-clear` never deletes silently: without `--yes` it only lists the
files it would remove.

### Scheduler anchor

`latest` prints the latest closed bar opening timestamp per symbol ×
timeframe from the cache — the anchor a future event-driven scheduler will
poll:

```bash
.venv/bin/python -m src.main latest
```

## Usage

```bash
.venv/bin/python -m src.main status          # full startup workflow + report
.venv/bin/python -m src.main symbols         # all available broker symbols
.venv/bin/python -m src.main symbols gold    # filtered search
.venv/bin/python -m src.main sync            # sync history for monitoring universe
.venv/bin/python -m src.main scan            # multi-timeframe market-state table
.venv/bin/python -m src.main latest          # latest closed bar per symbol × timeframe
.venv/bin/python -m src.main analyze XAUUSD  # detailed Ichimoku analysis
.venv/bin/python -m src.main history-clear   # list cached history (no delete)
.venv/bin/python -m src.main history-clear --yes  # delete cached history
```

### First safe real-data synchronization

The Parquet cache currently contains mock-generated data. Do not mix mock
history with real broker history:

```bash
.venv/bin/python -m src.main history-clear --yes   # removes mock cache
./scripts/start-mt5-bridge.sh
.venv/bin/python -m src.main sync                  # real OHLC from the broker
```

`history-clear` never deletes silently: without `--yes` it only lists the
files it would remove.

### Startup workflow

```
START
 ├── Initialize MT5 (via bridge)
 ├── Verify connection
 ├── Read account information
 ├── Calculate account health
 ├── Discover ALL available account symbols
 ├── Load preferred logical symbols
 ├── Resolve preferred → broker symbols
 ├── Discover every open position
 ├── Add position symbols to monitoring universe
 ├── Synchronize historical data
 ├── Calculate indicators
 ├── Determine market states
 └── Display/report results
```

Symbol discovery always happens before preferred-symbol resolution, and the
connected account is the source of truth for what instruments exist.

### Symbol resolution

Preferred symbols are user intent, not broker names. They are resolved
conservatively against the account's actual symbol list:

1. explicit mapping (always wins),
2. exact name match,
3. unique prefix + known-suffix match (`XAUUSD` → `XAUUSDc`),
4. otherwise reported as **ambiguous** (multiple candidates) or **missing** —
   never guessed. Ambiguity requires an explicit mapping in
   `config/symbols.yaml`.

The real broker uses broker-specific names (e.g. `XAUUSDc`); the suffix is
never assumed — discovery is fully dynamic.

### Monitoring universe

```
preferred resolved symbols + all open-position symbols = active monitoring universe
```

An open position is never ignored just because its symbol is not configured
as preferred.

### Market-state classification

`src/indicators/ichimoku.py` computes raw Ichimoku values (Tenkan 9, Kijun 26,
Senkou B 52, displacement 26 — pure pandas, no opaque TA library).
`src/analysis/market_state.py` interprets them deterministically (no LLM).

**Current Kumo vs Projected Kumo.** Price vs Kumo uses the plotting-aligned
(shifted) spans — the cloud located at the current candle. Projected Kumo
uses the unshifted current calculations — the cloud that will be plotted 26
bars ahead. The two are never conflated.

**Chikou.** The current close is evaluated against the historical price
structure at the 26-bars-back location: above the historical high AND above
the historical Kumo → BULLISH (clean); below both → BEARISH (clean); above
one but entangled with the Kumo → directional but obstructed; inside the
historical range → NEUTRAL.

| Component        | Values                          |
|------------------|---------------------------------|
| Price vs Kumo    | ABOVE / INSIDE / BELOW          |
| Tenkan vs Kijun  | BULLISH / NEUTRAL / BEARISH     |
| Projected Kumo   | BULLISH / NEUTRAL / BEARISH     |
| Chikou           | BULLISH / NEUTRAL / BEARISH (+ obstructed flag) |
| Kijun slope      | RISING / FLAT / FALLING         |
| Kumo thickness   | normalized to ATR(14)           |

**Direction + Condition.** `direction` (established trend) requires price
position to be confirmed by structure; `condition` (regime) keeps
contradictions visible:

| Condition        | Meaning                                        |
|------------------|------------------------------------------------|
| ESTABLISHED      | direction confirmed, no opposing structural votes |
| TRANSITION       | direction present but weakly supported         |
| REVERSAL_ATTEMPT | price position opposes a strong structural majority |
| MIXED            | components contradict without a clear split   |

A price below the Kumo with every structural component bullish is a
NEUTRAL direction with a REVERSAL_ATTEMPT condition — never an established
bullish market. The numeric score remains as a diagnostic summary only; it
never obscures the component state. The analyzed candle (opening timestamp,
`Closed: YES`) is shown with every result.

### Account health

Deterministic and configuration-driven (`config/risk.yaml`). Rules are
evaluated in priority order; the worst triggered state wins
(CRITICAL > WARNING > HEALTHY). Trading-disabled accounts are CRITICAL.

## Project layout

```text
mt5-trading-agent/
├── .env / .env.example / .gitignore / README.md / requirements.txt
├── bridge/           # mt5_bridge.py (Wine-side read-only HTTP bridge)
├── config/           # symbols.yaml, risk.yaml
├── data/history/     # per-symbol per-timeframe Parquet files
├── logs/             # rotating agent.log, bridge.log, bridge.pid
├── scripts/          # start/stop/check-mt5-bridge.sh
├── src/
│   ├── main.py       # CLI
│   ├── config.py     # .env + YAML config, logging
│   ├── mt5/          # provider abstraction + MT5 integration
│   │   ├── provider.py    # TradingProvider ABC, MT5Provider
│   │   ├── remote.py      # RemoteMT5Provider (HTTP bridge client)
│   │   ├── closure.py     # closed-candle determination (broker-time based)
│   │   ├── connection.py  # terminal lifecycle (init/login/shutdown)
│   │   ├── account.py     # account retrieval
│   │   ├── symbols.py     # discovery + SymbolResolver
│   │   ├── positions.py   # open-position discovery
│   │   ├── history.py     # Parquet store, sync, validation
│   │   └── mock.py        # synthetic provider for dev/testing
│   ├── indicators/    # ichimoku.py (raw math)
│   ├── analysis/      # account_health.py, market_state.py (interpretation)
│   └── models/        # account, symbol, position, market, tick dataclasses
└── tests/             # unit tests (no live MT5 required)
```

## Research history

Deep, read-only broker-history acquisition and explicit research replay are
documented in [docs/research-history.md](docs/research-history.md). Normal
history sync remains lightweight.

## Testing


```bash
.venv/bin/python -m pytest tests/ -v
```

Tests cover Ichimoku calculation (hand-computed values, current vs projected
spans), Chikou directional confirmation, market-state direction/condition
classification, symbol matching/resolution, account-health classification,
history merge/deduplication/validation, the closed-candle invariant and cache
repair, mock-provider determinism, read-only guarantees, and
`RemoteMT5Provider` against a fake local HTTP bridge. No live MT5 connection
is required.

## Logging

Rotating file logs (`logs/agent.log`, 5 × 1 MB) plus console. Connection,
account retrieval, symbol discovery/resolution, position discovery, history
sync, missing bars and analysis errors are logged. Credentials are never
logged.

## Future phases (not implemented)

VCZ Area-of-Interest/revisit research lifecycle (definitions pending), position manager, risk engine,
trade journal, execution backtesting, Hermes/LLM integration, news/event analysis, Telegram
interface, remote MT5 execution, automated SL/TP management, partial closing,
trade execution.
The architecture keeps these addable without rework.
# mt5-agent
