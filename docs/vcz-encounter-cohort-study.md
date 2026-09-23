# VCZ Encounter Cohort Study V1 — XAUUSDc

## Question and method

When completed price candles overlap surviving PVSRA price memory, what raw future movement differences appear across cohorts, years, and native timeframes? This is an offline description of persisted Encounter V1 records. The study reads each timeframe independently, uses its existing 1/4/8/16/32-bar outcomes, and groups **one dimension at a time**. It did not alter VCZ V1 or Encounter V1, fetch broker data, tune buckets, define AOI, or rank cohorts.

**ALL** retains every encounter. **FIRST** uses `encounter_ordinal == 1`, at most one row per encountered VCZ copy, and is the primary zone-level population. ALL rows are dependent: adjacent encounters of the same zone have overlapping future windows. FIRST reduces that repetition, but two copies can share a PVSRA source, overlap geometrically, meet the same candle, and have overlapping future windows. No significance test or independence claim is made.

Source: stored `XAUUSDc` encounter Parquet, with H4 already present; M15/H1/D1 were regenerated offline from saved native candles through the existing Encounter V1 adapter. Stored candle ranges: M15 2022-06-07–2026-09-21 (100,659); H1 2019-07-04–2026-09-21 (42,214); H4 2019-07-04–2026-09-21 (11,536); D1 2019-07-04–2026-09-21 (2,244). Early years are sparse in several encounter datasets. Cross-timeframe full-period medians therefore do not use identical calendar coverage. Four or 16 native bars also represent different wall-clock durations across timeframes.

Age buckets are fixed at 0–1, 2–4, 5–16, 17–64, 65–256, 257–1024, and 1025+ **native bars**. The pre-encounter remaining fraction is `(pre_top-pre_bottom)/(original_top-original_bottom)`. Buckets are `>0.75` for (0.75,1], `0.50-0.75` for (0.50,0.75], `0.25-0.50` for (0.25,0.50], `0.10-0.25` for [0.10,0.25], and `<0.10` for [0,0.10). Zero-height originals are `UNAVAILABLE`. No boundary was changed after examining the data.

Tables below report H4 four-bar medians. Up/down excursion is in XAUUSDc price units; absolute close return is a percentage. Every cohort row has its `n`; almost all H4 four-bar outcomes are available, and detailed `n_available` is in the CSV. Small cohorts remain in exports with `small_sample=true` when `n<30`.

## H4 inventory and ALL versus FIRST

H4 had **3,142 encounters**, **1,357 unique encountered zones**, and **1,012 unique PVSRA source candles**. FIRST has 1,357 rows; later encounters contribute 1,785 ALL rows. Encounter candles meeting 1, 2, or 3+ zones numbered 1,601, 447, and 182 respectively. These are candle counts, not independent observations.

| Population | n | n available @4 | Median up | Median down | Median absolute close return |
|---|---:|---:|---:|---:|---:|
| ALL | 3,142 | 3,141 | 17.72 | 17.19 | 0.534% |
| FIRST | 1,357 | 1,356 | 19.69 | 17.76 | 0.554% |

The ordinal view of ALL had 1,357 first, 846 second, and 939 third-or-later encounters. Their four-bar median upward excursions were 19.69, 16.85, and 16.27 respectively; this comparison is affected by repeated-zone dependence and differing age/period composition.

## H4 age and remaining fraction

| FIRST age (bars) | n | Median up | Median down | Median absolute return |
|---|---:|---:|---:|---:|
| 0–1 | 502 | 20.17 | 19.18 | 0.619% |
| 2–4 | 441 | 19.35 | 15.96 | 0.518% |
| 5–16 | 229 | 17.08 | 19.04 | 0.440% |
| 17–64 | 120 | 21.61 | 17.57 | 0.730% |
| 65–256 | 44 | 18.03 | 25.71 | 0.550% |
| 257–1024 | 21 | 23.87 | 6.33 | 0.526% |
| 1025+ | 0 | — | — | — |

The 257–1024 cohort is below the display threshold; 1025+ is empty. The age medians are not monotonic. In 2024/2025/2026, 5–16-bar median upward excursions were 7.88/19.31/37.27, while 0–1-bar values were 12.02/22.40/32.62: even that pair changes order in 2026.

| FIRST pre-remaining fraction | n | Median up | Median down | Median absolute return |
|---|---:|---:|---:|---:|
| >0.75 | 144 | 18.86 | 15.59 | 0.542% |
| 0.50–0.75 | 347 | 18.68 | 19.32 | 0.555% |
| 0.25–0.50 | 411 | 19.48 | 16.91 | 0.539% |
| 0.10–0.25 | 276 | 20.00 | 16.99 | 0.553% |
| <0.10 | 179 | 22.51 | 17.84 | 0.659% |

The <0.10 fragment cohort is present and has a larger pooled H4 median upward excursion than >0.75, but its yearly comparison changes: in 2024 it was 12.94 versus 10.99 (n=35/35), in 2025 22.63 versus 19.72 (n=77/56), and in 2026 32.62 versus 42.43 (n=59/46). The fraction describes recovered footprint only; it is not a zone-quality measure.

## H4 selector, PVSRA, recovery and Ichimoku

The following are **FIRST** cohorts at four H4 bars. Each dimension is analyzed separately.

| Dimension | Cohort | n | Median up | Median down | Median absolute return |
|---|---|---:|---:|---:|---:|
| Selector | ABOVE (Pine direction=1) | 669 | 20.20 | 16.52 | 0.544% |
| Selector | BELOW (Pine direction=0) | 688 | 19.07 | 20.61 | 0.556% |
| Encounter PVSRA | NORMAL | 850 | 19.87 | 16.25 | 0.580% |
| Encounter PVSRA | ABOVE_AVERAGE | 334 | 19.70 | 20.62 | 0.520% |
| Encounter PVSRA | CLIMAX | 173 | 17.74 | 23.29 | 0.540% |
| Source PVSRA | ABOVE_AVERAGE | 1,026 | 19.71 | 17.99 | 0.533% |
| Source PVSRA | CLIMAX | 331 | 19.03 | 16.88 | 0.610% |
| Source direction | BULLISH | 639 | 18.24 | 19.04 | 0.540% |
| Source direction | BEARISH | 718 | 20.45 | 16.88 | 0.570% |
| Same-candle recovery | PARTIALLY_RECOVERED | 872 | 19.66 | 16.94 | 0.565% |
| Same-candle recovery | FULLY_RECOVERED | 485 | 19.73 | 19.18 | 0.544% |
| Kumo position | ABOVE_KUMO | 735 | 19.35 | 17.57 | 0.530% |
| Kumo position | INSIDE_KUMO | 159 | 16.45 | 14.48 | 0.470% |
| Kumo position | BELOW_KUMO | 463 | 20.27 | 20.06 | 0.650% |
| Kijun position | ABOVE_KIJUN | 749 | 18.23 | 16.49 | 0.523% |
| Kijun position | BELOW_KIJUN | 608 | 21.15 | 20.34 | 0.594% |
| Kumo orientation | BULLISH | 867 | 19.66 | 17.99 | 0.525% |
| Kumo orientation | BEARISH | 489 | 19.73 | 17.39 | 0.612% |
| Kumo orientation | FLAT | 1 | 31.10 | 2.01 | 1.171% |

No FIRST H4 recovery row was UNCHANGED; ALL had one. Recovery effect is a mechanical same-candle observation, not a future prediction. `FLAT` Kumo orientation has only one observation. The cohort CSV retains all small rows. Encounter V1 persisted Kijun values as `ABOVE_ZONE`/`BELOW_ZONE`; this study maps them to `ABOVE_KIJUN`/`BELOW_KIJUN` for labels and does not recalculate Ichimoku.

## Year comparison

The usable H4 FIRST population is concentrated in 2024–2026 (338, 551, and 416 rows); 2019–2023 year counts are 4, 4, 27, 8, and 9. The table shows four-bar first encounters, with `n_available` one less than `n` only for 2026.

| Year | n | Median age | Median remaining | Median up @4 | Median down @4 | Median abs return @4 | Median up @16 | Median down @16 | Median abs return @16 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024 | 338 | 2 | 0.413 | 12.11 | 11.19 | 0.480% | 27.35 | 21.53 | 1.040% |
| 2025 | 551 | 2 | 0.372 | 20.79 | 16.10 | 0.510% | 43.44 | 30.76 | 1.290% |
| 2026 | 416 | 2 | 0.375 | 36.79 | 36.76 | 0.830% | 68.13 | 77.39 | 1.710% |

Absolute price excursions and absolute close returns increased substantially across those years even though median age and remaining fraction changed less. This period variation limits pooled comparisons. For example, H4 BELOW_KUMO versus ABOVE_KUMO four-bar median absolute return was 0.468% versus 0.526% in 2024 (n=137/156), 0.566% versus 0.488% in 2025 (n=105/394), and 0.973% versus 0.582% in 2026 (n=200/165). Pooled relationships can therefore reverse between years. Year-by-year rows for every dimension are in the cohort exports.

## Native-timeframe comparison

All metrics below use FIRST. `@4` and `@16` are native bars and are not equal elapsed times across rows. The stored histories have different start dates.

| Timeframe | Candles | ALL encounters | Unique zones / sources | FIRST | Median age | Median pre-remaining | Up/down/abs return @4 | Up/down/abs return @16 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| M15 | 100,659 | 38,479 | 17,678 / 14,788 | 17,678 | 2 | 0.353 | 4.95 / 4.68 / 0.144% | 9.28 / 8.92 / 0.270% |
| H1 | 42,214 | 9,536 | 3,984 / 3,230 | 3,984 | 2 | 0.357 | 8.60 / 8.67 / 0.263% | 19.60 / 17.33 / 0.567% |
| H4 | 11,536 | 3,142 | 1,357 / 1,012 | 1,357 | 2 | 0.383 | 19.69 / 17.76 / 0.554% | 40.80 / 33.12 / 1.290% |
| D1 | 2,244 | 1,082 | 550 / 449 | 550 | 1 | 0.351 | 32.14 / 24.70 / 1.305% | 73.81 / 42.70 / 2.553% |

M15/H1/H4 first-encounter medians for age and pre-remaining fraction are numerically similar; D1 age is one bar. Encounter CLIMAX had larger four-bar median absolute close return than NORMAL in each of 2024–2026 on M15 and H1; H4 did not reproduce that yearly ordering consistently. BELOW_KUMO and BELOW_KIJUN often had larger absolute returns than their ABOVE counterparts on M15/H1 in those years; H4 and D1 had mixed or sparse annual comparisons. These are observations across different native bars, coverage, and cohort compositions, not pooled effects.

## Outputs and limitations

Machine-readable CSVs and deterministic metadata JSON are under `data/research/vcz/XAUUSDc_<timeframe>_cohorts.csv` for M15, H1, H4, D1. Each long row has population, timeframe, period type/year or quarter, one dimension/cohort, horizon, `n`, `n_available`, raw movement medians and quartiles, age/remaining summaries, same-candle recovery counts/rates, recovery-by-horizon count, and `small_sample`. The encounter Parquets and cohort exports are local ignored research artifacts. The default threshold of 30 flags small rows; it never drops them. Outcome availability censors incomplete future windows. Full recovery beyond the saved horizon or history end is unknown, not zero or infinite.

The CLI is `.venv/bin/python -m src.main vcz-encounter-study XAUUSDc --timeframe H4 --research-history`; `--population`, `--segment quarter`, repeatable `--dimension`, `--min-sample`, `--horizons`, and CSV/Parquet `--output` are supported. Repeat runs over existing artifacts took approximately 7.1 s H4, 7.8 s M15, 7.3 s H1, and 7.3 s D1 in this workspace; those times exclude missing-artifact encounter regeneration.

## WHAT THE DATA SUPPORTS

Persisted encounters can be counted and compared by native timeframe, population, zone age, pre-encounter footprint, PVSRA, VCZ selector, recovery mechanics, and Ichimoku context. FIRST and ALL produce distinct H4 summaries. Some M15/H1 PVSRA and structural-context movement differences appeared in several well-populated years. H4 age and pre-remaining fraction do not show a simple monotonic relation to four-bar movement; the <0.10 H4 cohort's pooled difference versus >0.75 changed direction in 2026.

## WHAT THE DATA DOES NOT SUPPORT

These descriptive comparisons do not establish independent observations, causation, prediction, a trading edge, a preferred timeframe, a superior VCZ side, or a zone ranking. The years and native timeframes differ in coverage and movement scale; sparse early years and D1 subcohorts limit comparisons. No AOI, entries, stops, targets, optimization, ML, or execution behavior was defined.

## OPEN QUESTIONS BEFORE DEFINING AOI

Would relationships remain similar after matching calendar coverage and describing the background movement distribution? How much dependence remains between paired zones and simultaneous multi-zone candles? Are the same cohort differences visible at fixed elapsed-time horizons rather than native-bar horizons? How should recovery censoring and tiny residual fragments be represented when the stored history ends? These are research questions, not proposed filters.
