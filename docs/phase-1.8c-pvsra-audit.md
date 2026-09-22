# Phase 1.8C PVSRA audit

Source: `references/cloudgazer.pine`, PVSRA settings and the “PVSRA + VWAP
DISPLACEMENT” block.

## Exact formulas

The configurable defaults are:

```text
volLen    = 20
climaxMul = 2.0
aboveMul  = 1.2
```

All moving averages are Pine `ta.sma` calculations over `volLen` active-chart
bars and include the current bar:

```text
volume_ma             = SMA(volume, 20)
spread                = high - low
spread_ma             = SMA(spread, 20)
vwap                  = ta.vwap(hlc3)
vwap_displacement     = abs(close - vwap)
vwap_displacement_ma  = SMA(vwap_displacement, 20)
```

The conditions are:

```text
climax_volume    = volume >= volume_ma * 2.0
above_volume     = volume >= volume_ma * 1.2
spread_expansion = spread >= spread_ma * 1.5
vwap_expansion   = displacement >= displacement_ma * 1.5

climax = climax_volume and (spread_expansion or vwap_expansion)
above  = not climax and above_volume
```

Classification precedence is therefore `CLIMAX`, `ABOVE_AVERAGE`, then
`NORMAL`. Every threshold uses `>=`, so equality qualifies. High volume alone
does not produce `CLIMAX`; one secondary expansion condition is also required.

Pine direction is:

```text
close > open: BULLISH
close < open: BEARISH
close == open: neither; represented as NEUTRAL in Python
```

The final Pine output is bar color. Green/red distinguish bullish/bearish
climax bars, blue/violet distinguish bullish/bearish above-volume bars, and
ordinary bull/bear colors cover normal bars. A doji receives no PVSRA color.
Colors and engulfing color override are visual behavior and do not enter the
Phase 1.8C confirmation model.

## Insufficient history and unavailable inputs

Pine `ta.sma` is `na` before 20 valid observations, so its vector conditions
cannot become true. Phase 1.8C exposes this explicitly as `UNAVAILABLE`
instead of treating the bar as normal. Missing usable volume or VWAP also
produces `UNAVAILABLE`; unavailable measurements remain `None`.

## Compatibility

The Python engine reuses Phase 1.8A's audited chart-timeframe session VWAP and
broker D1 boundaries. MT5 has a different data feed from TradingView. The
engine prefers a complete, nonnegative `real_volume` series with at least one
positive observation through the evaluated candle, otherwise a similarly
usable `tick_volume` series. Exness CFD `real_volume` has been observed as all
zero, so those instruments use `TICK_VOLUME`. Tick counts are deterministic
broker data but are not claimed to equal TradingView volume.
