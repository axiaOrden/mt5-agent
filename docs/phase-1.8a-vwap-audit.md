# Phase 1.8A VWAP semantics audit

## Finding

Cloudgazer contains one VWAP definition:

```pine
hlcVwap = ta.vwap(hlc3)
```

It supplies no anchor and makes no `request.security()` or lower-timeframe
request for this value. Its crosses directly compare chart `close` with that
series.

TradingView documents its built-in daily VWAP as equivalent to accumulating
`hlc3 * volume / volume` and resetting on `timeframe.change("1D")`. Pine code
executes on the active chart dataset unless the indicator declaration or an
explicit data request selects another timeframe. Cloudgazer does neither.

Therefore Cloudgazer's exact behavior is:

1. Reset on the first chart bar belonging to a new symbol trading day.
2. Accumulate the active chart's OHLCV bars only.
3. Recompute independently after a chart timeframe change.
4. Do not use lower-timeframe data internally for H1, H4, or D1.
5. On D1, reset on every bar, so VWAP equals that bar's HLC3.
6. On H4, reset on the first H4 bar whose daily dataset has changed. Pine
   cannot divide that H4 bar at a session boundary using unseen intrabars.
7. Permit `ta.crossover()`/`ta.crossunder()` across the reset because those
   functions still compare the current and previous series values.

The same algorithm applies to forex, CFDs, equities, and futures. Results
differ because the symbol feed controls bar alignment, sessions, and volume
units. Similar-looking VWAPs across chart timeframes are not guaranteed.

## Python interpretation

`session_vwap()` uses the analyzed timeframe's bars and resets at broker D1
open timestamps. The CLI loads D1 history for these boundaries. Since cached
D1 history deliberately excludes the current forming D1 candle, the most
recent observed daily cadence is extended in 24-hour increments through the
latest intraday bar. This uses no local time and consumes no forming OHLCV.

MT5 `tick_volume` is the weighting field. It is a count of broker ticks and
is not guaranteed to equal TradingView feed volume. A missing or entirely
zero volume session yields undefined VWAP and cannot emit a VWAP cross.

The UTC-date grouping remains available only as an explicit fallback for
historical callers without D1 boundary data. The live CLI fails closed if it
cannot obtain broker D1 boundaries.

## Compatibility limits

- TradingView and Exness can have different session calendars and feeds.
- A DST change in the currently forming broker day cannot be discovered from
  closed D1 bars alone; the extended last-known cadence can be off until that
  D1 candle closes.
- MT5 tick volume can differ materially from TradingView volume.
- No canonical M15 profile was added because it would not reproduce the Pine
  expression. Such a profile would be a separate future analytical feature.

## Authoritative references

- TradingView Pine error documentation, “Replacing custom code with
  built-ins demo”: defines daily VWAP with `timeframe.change("1D")` and says
  it produces the same result as `ta.vwap`.
- TradingView Pine chart information: chart OHLCV variables belong to the
  current dataset; scripts need explicit timeframe/data requests to use a
  different dataset.
- TradingView VWAP documentation: session anchoring on 1D is not useful
  because it resets on every bar.
