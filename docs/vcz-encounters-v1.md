# VCZ Encounter Observation V1

This read-only study records every completed native-timeframe candle whose closed high–low interval intersects a surviving VCZ's **pre-candle** bounds. An endpoint touch counts. A zone created during that candle cannot be encountered until a later candle. Each zone and candle pair has a stable identifier; repeated overlapping candles receive increasing per-zone ordinals.

The engine calls the existing VCZ V1 replay for authoritative zone creation and lifecycle, then uses the same V1 recovery function while scanning forward. The encounter stores pre and post bounds, overlap width divided by pre-zone height, previous completed close position relative to the pre-zone, recovery effect, source and encounter PVSRA facts, and current-candle Ichimoku structure. Price versus Kumo and Kumo orientation use the cloud plotted at the encounter candle, not projected spans. Insufficient indicator history yields `UNAVAILABLE`. Equality with Kijun is `AT`; equality with a Kumo boundary is `INSIDE`.

Forward horizons default to 1, 4, 8, 16, and 32 native bars. Each outcome uses only subsequent bars and reports raw close return, highest high, lowest low, and upward/downward distance from the encounter close. An incomplete horizon is unavailable. Recovery by a horizon is unavailable with that incomplete horizon; when available, bars until recovery is measured from the encounter candle and can be zero if recovery occurred on that candle. These observations have no directional profit interpretation. The core consumes supplied closed candles and PVSRA facts only; it does not contact MT5.

Run offline with saved research candles:

```sh
.venv/bin/python -m src.main vcz-encounters XAUUSDc --timeframe H4 --research-history
```

`--from` and `--to` select encounter candle dates after full-history replay, preserving warmup and future outcome data. `--horizons 1,4,8` chooses positive distinct native-bar horizons. `--output` selects Parquet destination; the default is `data/research/vcz/<symbol>_<timeframe>_encounters.parquet`. One flat row is written per encounter. The CLI only reads stored H4 and D1 research history, and does not sync or trade.

This layer deliberately does not change zone recovery, PVSRA, Ichimoku, signal replay, or cohort analysis. A candle can encounter multiple zones and both VCZ sides. No nearest-zone or reaction label is assigned. Missing encounters for zones recovered on their creation candle follow directly from the pre-candle eligibility rule.

## Saved XAUUSDc H4 validation

The stored H4 research history contained 11,536 candles. Replay created 2,134 VCZs and recorded 3,142 encounters across 1,357 distinct zones: 1,357 first encounters and 1,785 later encounters. Encounter-bar recovery effects were 1,854 partial, 1,287 full, and 1 unchanged. Encounter-bar PVSRA classifications were 1,890 normal, 821 above average, and 431 climax. Price was above the current-location Kumo on 1,707 encounters, below on 1,048, and inside on 387.

At the four-bar horizon, 3,141 outcomes were complete. Median raw close returns were 0.0832% for first encounters and 0.0667% for later encounters. By encounter-bar PVSRA class, medians were 0.0931% normal, 0.0412% above average, and 0.0644% climax. These are descriptive signed price changes, not trade returns; cohort overlap and repeated zones prevent interpreting them as independent trials.
