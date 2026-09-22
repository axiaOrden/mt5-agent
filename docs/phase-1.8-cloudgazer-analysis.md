# Phase 1.8 investigation: Cloudgazer signal intelligence

Source: `references/cloudgazer.pine` (1,509 lines). This is an analysis of the complete indicator, not an implementation plan or a change to Phase 1.7.

## How the trading signal actually works

The only inputs to the main FLAT/LONG/SHORT state machine are two crossover pairs: Tenkan versus Kijun, and close versus `ta.vwap(hlc3)`. A crossover means the relationship changes across consecutive chart bars; equality/`na` and insufficient history need explicit handling in a Python version. The events are evaluated on the *chart timeframe*. Cloudgazer does not combine M15, H1, H4, and D1 states or consult a higher timeframe for its main transitions.

The VWAP cross has priority. The ordered branch chain is `vwapCrossUp`, `vwapCrossDown`, `crossUp`, `crossDown`. Thus a bullish VWAP cross suppresses a simultaneous bearish TK cross even if the current state is already LONG and no new label results. The suppressed TK event is still a raw market event, but it does not drive the Pine state machine on that bar. Symmetrically for bearish VWAP crosses. A TK bullish and bearish cross cannot normally coincide; the same applies to VWAP's two directions.

| Current position | Winning event | New position | Emitted label |
|---|---|---|---|
| FLAT | VWAP up | LONG | BUY |
| SHORT | VWAP up | LONG | BUY |
| LONG | VWAP up | LONG | none |
| FLAT | VWAP down | SHORT | SELL |
| LONG | VWAP down | SHORT | SELL |
| SHORT | VWAP down | SHORT | none |
| FLAT | TK up | LONG | BUY if `close > spanA` **and** `close > spanB`; otherwise WB |
| SHORT | TK up | LONG | BUY, regardless of cloud |
| LONG | TK up | LONG | none |
| FLAT | TK down | SHORT | SELL if `close < spanA` **and** `close < spanB`; otherwise WS |
| LONG | TK down | SHORT | SELL, regardless of cloud |
| SHORT | TK down | SHORT | none |
| any | no cross | unchanged | none |

No transition returns to FLAT after initialization. Repeated same-direction events are suppressed as labels/alerts, although raw crossover conditions can recur after intervening opposite crosses. A suppressed higher-priority VWAP event can prevent a lower-priority TK transition. `bullConfirmed`/`bearConfirmed` only change the FLAT-entry label for a TK event. They do not gate the transition and do not apply to VWAP events or reversals. WB/WS are therefore LONG/SHORT transitions with weak/unconfirmed labels, not a wait state.

The main `send_alert` is invoked only when a label is emitted. It calls `alert(..., alert.freq_once_per_bar_close)` and includes the position, signal label, OHLC, chart volume and VWAP. The state machine and label creation themselves are not guarded by `barstate.isconfirmed`; Pine can recalculate on a live forming bar. The alert frequency requests a close-time alert, but the code's live label/state execution must not be copied as a Python intrabar strategy. Phase 1.8 should evaluate a finalized bar once, after broker-tick-based closure, and give events stable `(symbol, timeframe, bar-open-time)` identity. Separate `alertcondition` calls exist for engulfing candles; these are independently selectable TradingView alerts, not main position alerts.

## Ichimoku comparison

Cloudgazer computes `getDonchian(len, close) = (lowest(close, len) + highest(close, len))/2`. **This uses closing prices**, unlike standard Ichimoku's highest high/lowest low and unlike `src/indicators/ichimoku.py`, which uses highs/lows. Tenkan uses 9 closes, Kijun 26 closes, Span A their midpoint, and Span B 52 closes. `spanA` and `spanB` are calculated on the current bar; plotting moves them forward by `kijunsen - 1` (25 with defaults). Chikou is the current close plotted back by `kijunsen - 1` (25). The Python implementation uses standard high/low midpoints and a displacement of 26. Its current-location cloud is shifted from calculations 26 bars earlier, and its projected cloud uses current calculations. Pine `bullConfirmed`/`bearConfirmed` compare the close to the **unshifted, current-calculation** spans, effectively the projected cloud values, not to the cloud visually located at today's bar. They are not Kumo breakouts. Chikou is plotted only; it never confirms a Cloudgazer state transition.

The Phase 1.7 model deliberately answers a different question: `market_state.py` uses price versus the cloud aligned with the current bar, TK relation, projected cloud, Chikou obstruction, Kijun slope and ATR-normalized cloud thickness to classify direction/condition. Preserve those semantics. If Pine compatibility is wanted in Phase 1.8, calculate the close-based TK values in a clearly named separate signal profile. A standard high/low TK event may also be useful, but it must not be labeled an exact reproduction of the Pine cross.

## Feature classification

| Feature | Classification | Actual role in Cloudgazer |
|---|---|---|
| TK bullish/bearish cross | SIGNAL EVENT | Main position transition, below VWAP priority. |
| Close/VWAP bullish/bearish cross | SIGNAL EVENT | Highest-priority main position transition. |
| Close above/below both unshifted spans | CONFIRMATION | Changes only FLAT TK entry label BUY/SELL versus WB/WS. |
| Tenkan/Kijun levels, spans, projected cloud color | TREND / MARKET CONTEXT | Underlying values/plots; no Kumo breakout test. |
| Chikou | VISUALIZATION ONLY | Back-shifted close plot; no decision use. |
| PVSRA climax/above-volume, spread expansion, VWAP displacement | CONFIRMATION | Compute vector candle color; do **not** enter main state machine or alert payload as conditions. Potential future context. |
| Bullish/bearish engulfing | SIGNAL EVENT | Separate event with selectable `alertcondition` and candle highlight; no main state transition. |
| Weekly session Psy high/low and 50%/61.8% crosses | SUPPORT / RESISTANCE CONTEXT | RB/RS/GB/GS labels are separate chart events, confirmed-bar gated, and do not change main position. Their crossover can be modeled as an optional level event later. |
| Daily/weekly highs/lows, daily pivots, tomorrow pivot | SUPPORT / RESISTANCE CONTEXT | Plotted levels only; no main signal condition. Tomorrow pivot uses current daily OHLC and is unsafe for historical intraday decisions. |
| ADR | VISUALIZATION ONLY | `adr` is computed but not referenced later; `aDRRange` input is unused (calculation hardcodes 14). |
| Trend Scouter short/long/custom channels | TREND / MARKET CONTEXT | Swing/channel computations only feed line drawing and colors; no state-machine input. |
| VCZ/vector candle zones | SUPPORT / RESISTANCE CONTEXT | Boxes created from previous vector candles and updated by price; no main signal input. |
| Main BUY/SELL/WB/WS labels, JSON alert, chart URL/colors | ALERT / UI ONLY | Output of a state transition. |
| Daily/weekly level labels, pivot/channel/cloud plots, bar colors | VISUALIZATION ONLY | Display; do not infer strategy rules from visibility. |

PVSRA specifics: `volMA = sma(volume, 20)`; climax volume is `volume >= 2.0 * volMA`; above volume is `volume >= 1.2 * volMA` only when not climax. Climax additionally needs `high-low >= 1.5 * sma(high-low, 20)` **or** `abs(close-VWAP) >= 1.5 * sma(abs(close-VWAP), 20)`. Bullish/bearish direction is `close > open` / `< open`; doji has no vector color. Engulfing is real-body coverage of the previous opposite-color body, with inclusive open/close boundaries. Engulfing color overrides vector color for display. VCZ's color-to-flag conversion consequently may not recognize a vector candle when engulfing override is active; VCZ remains a display subsystem, not a reliable source of vector events.

TradingView's `volume` is whatever its data feed supplies for that instrument. The script never selects real versus tick volume. MT5 history retains both `tick_volume` and `real_volume`; the mock currently sets `real_volume` to zero. Exact TradingView equivalence is not guaranteed. A future MT5 PVSRA feature should explicitly select a nonzero, consistently available volume field per instrument/provider, label its provenance, and calculate its moving baseline from the same field. Do not silently mix real and tick volume or call them equivalent.

## Closed bars, higher timeframes, and lookahead

The current project defaults to M15/H1/H4/D1 (`src/config.py`). `src/mt5/history.py` fetches completed bars using MT5 position 1, merges cached bars by timestamp, and filters by the latest broker tick. `src/analysis/market_state.py` filters again when broker tick time is supplied. `src/mt5/closure.py` defines closure as bar open plus timeframe duration no later than broker tick time. This is the required Phase 1.8 input boundary. The history sync has a tick-unavailable fallback that assumes returned data are closed; a strategy event runner should fail closed or defer emission when broker closure cannot be verified, especially after range fetch/cache merge. `fetch_rates_since` uses local UTC time as an API range end, but closure is decided using broker tick time when available; never turn local time into the event closure authority.

Cloudgazer uses `request.security(..., lookahead_on)` for daily OHLC and daily/weekly highs/lows. Prior daily OHLC requested at offset 1 is a completed-period value; current-period OHLC at offset 0, current daily/weekly highs/lows and `pp_tomorrow` must **not** be backfilled into historical intraday events as if known before the period evolved/closed. ADR uses daily `request.security` without explicit lookahead, yet is unused. Pine's forward cloud plot and backward Chikou plot are display offsets, not permission to access future bars. Python `chikou_span = close.shift(-26)` contains future closes at old rows; `market_state.py` instead compares today's close with price structure 26 bars ago, which is causal. Never consume historical shifted Chikou rows as event inputs. Session Psy levels can evolve while the session bar forms and depend on exchange/timezone/DST conventions; a later level event must use only finalized values available at its decision time.

## Recommended Phase 1.8 boundary

Keep `market_state.py` unchanged. A separate `signal_events.py` can emit raw, timestamped closed-bar TK and VWAP crosses first, with explicit `PINE_CLOSE` versus standard high/low formula selection. Add engulfing as a separate independent event. A Kumo breakout is **not present** in Cloudgazer; define it only if there is a separate strategy requirement, including which cloud alignment and bar-close crossing rule. PVSRA climax/above-volume can become provider-labeled confirmation, not a direct BUY/SELL trigger. Psy level crosses are optional support/resistance events with careful time alignment.

Apply the documented branch priority in a separate state-transition reducer, retaining raw events even when suppressed. The reducer should return the prior/new state, winning event, and emitted label; it must not be mistaken for a real MT5 position. Then annotate each event with current timeframe market state and the latest **already closed** higher-timeframe states available at that event's timestamp. Deterministic labels such as WITH_TREND, COUNTER_TREND, REVERSAL_ATTEMPT, and MIXED should be defined from explicit component rules, with stale/missing higher-timeframe data visible. Avoid confidence percentages. This architecture preserves Phase 1.7 as market description and makes Phase 1.8 an auditable account of what occurred.
