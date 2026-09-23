# VCZ V1: Pine-compatible price memory

Source audited: `references/cloudgazer.pine`. VCZ records where unusual PVSRA
activity occurred. Subsequent price action shrinks or fully recovers that
range. The recovering candle need not itself be a PVSRA vector.

## Pine audit

- Settings at lines 244–268: `showVCZ=true`, `zonesMax=20`; `zoneType` and
  `zoneUpdateType` each expose only `Body with wicks`. `zoneUpdateType` is
  passed to `updateZones` but not read there. Transparency, border, and color
  options affect drawing only.
- `getPvsraFlagByColor` at 366–387 maps green/red/blue/violet to
  +3/−3/+2/−2, light gray to +1, and all other colors to −1. The color
  expression at 763–772 gives CLIMAX and ABOVE_AVERAGE their vector colors
  only when `close > open` or `close < open`. A neutral doji has no color,
  even if its volume condition qualifies. Existing Python PVSRA facts are
  mapped to these flags without changing their classification formulas.
- The only calls to `updateZones` are at 1465 and 1486. Both receive the
  current chart `high, low, open, close` and the same `pvsra` flag. The first
  passes literal `direction=0` and `zoneBoxesBelow`; the second passes literal
  `direction=1` and `zoneBoxesAbove`. `direction` is a fixed array/recovery
  selector, **not** candle, PVSRA, market, or Cloudgazer direction. It does
  not change with the source candle. Every qualifying candle can therefore
  create two independent zones with the same original bounds.
- `updateZones` at 398–513 reads OHLC and `pvsra[1]`. Only flags ±2/±3
  create a box. The sole available `Body with wicks` option reduces its
  top/bottom ternaries to the source candle's high/low. The new box is
  unshifted *before* the update loop, so the current candle can shrink or
  fully recover it immediately.
- Selector 1 checks `close >= top OR high >= top` first, then strict interior
  `high` to raise bottom, then strict interior `close`. Selector 0 checks
  `close <= bottom OR low <= bottom` first, then strict interior `low` to
  lower top, then strict interior `close`. The V1 engine preserves this order.
  With valid OHLC, the close-only interior branches are unreachable because
  `high >= close` and `low <= close`; they remain in the implementation for
  source fidelity. Wicks can shrink or fully recover a zone.
- `cleanarr` at 390–395 removes deleted-box placeholders after both calls.
  `zonesMax` is applied inside each update call *before* that cleanup: if
  the pre-clean array length exceeds its limit, the oldest slot is popped,
  even if some other box was just deleted. An explicitly requested
  `max_zones=20` reproduces that display retention rule per array. Evicted
  records remain in research history and are not counted as fully recovered.
- A search of the complete supplied Pine file found **no VCZ 1000-bar
  lookup or reconstruction setting**. Its `1000` matches are millisecond
  conversions elsewhere in the script. V1 therefore has no invented 1000-bar
  limit. The research default processes the full supplied history and keeps
  every zone lifecycle record. Pine's arrays are retained across chart bars.

## Historical timing and scope

The Python engine consumes supplied, already closed native-timeframe bars and
their existing PVSRA results. At the close of bar *i*, it creates a zone from
bar *i−1* when that source qualifies, then applies bar *i*'s recovery checks.
The zone never appears in a snapshot before those facts are causally known.
Unlike Pine's live forming-bar drawing, historical V1 deliberately exposes
only completed-bar states.

`replay_vcz` is a pure deterministic engine. `vcz_as_of` replays only bars
closed by its cutoff. `replay_native_vcz` is an offline adapter that computes
native-timeframe PVSRA through the existing indexed Phase 1.8C implementation
from supplied historical bars and broker D1 session anchors. The `vcz`
command reads saved research history; it does not contact MT5 or Wine.

Each zone has a stable ID derived from symbol, timeframe, source bar timestamp,
PVSRA flag, and fixed Pine selector. Original geometry never changes.
Current geometry describes the remaining unrecovered part. `REMAINING` and
`FULLY_RECOVERED` are literal price-memory states; `DISPLAY_EVICTED` is used
only when an optional Pine array limit is applied. Partially recovered zones
are recognized from changed bounds. Fully recovered zones leave the surviving
collection but remain in historical records. Overlapping zones are updated
independently. A qualifying candle can update an older zone and create its
own zone when it becomes the previous completed bar on the next step.

VCZ is not a BUY/SELL signal, support/resistance classification, confirmation,
institutional-intent inference, entry selection, or revisit/Area-of-Interest
model. None of those interpretations is encoded by V1.

## Hand-checkable geometry traces

These examples use completed M15 candles. Both arrays receive the source
zone; each trace follows one of the independent copies. Times are UTC bar
opens. The zone first appears when the 00:15 candle closes at 00:30.

```text
UPWARD COPY (Pine direction=1)
SOURCE 00:00  flag=+3  O=95 H=100 L=90 C=96  original=[90,100]
NEXT   00:15  direction=1 O=88 H=94  L=85 C=89  remaining=[94,100]
NEXT   00:30  direction=1 O=95 H=97  L=92 C=95  remaining=[97,100]
FINAL  00:45  direction=1 O=98 H=100 L=97 C=98  FULLY_RECOVERED (wick)

DOWNWARD COPY (Pine direction=0)
SOURCE 00:00  flag=-2  O=95 H=100 L=90 C=94  original=[90,100]
NEXT   00:15  direction=0 O=102 H=105 L=98 C=102 remaining=[90,98]
NEXT   00:30  direction=0 O=99 H=101 L=95 C=99  remaining=[90,95]
FINAL  00:45  direction=0 O=91 H=93 L=90 C=91   FULLY_RECOVERED (wick)
```

The source flag describes its PVSRA color. The fixed `direction` values select
the Pine array branch; they do not change with the later candles.
