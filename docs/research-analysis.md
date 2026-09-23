# Phase 1.10 offline cohort analysis

`research-analyze` reads a Phase 1.9 events Parquet export. It does not load
configuration, contact MT5/Wine, replay signals, or derive forward outcomes.

```bash
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet --report pvsra
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet --report direction-pvsra
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet --report higher-timeframe
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet --report structural-alignment
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet --report cloudgazer-alignment
```

Custom grouping uses persisted categorical columns. `--list-fields` lists
the dimensions actually present in the artifact. The CLI alias `direction`
means the persisted `label` (BUY/SELL); `event_direction` is the persisted
BULLISH/BEARISH field. Multiple `--where FIELD=VALUE` options are combined
with AND. A persisted `UNAVAILABLE` state stays `UNAVAILABLE`; a null context
value is displayed and filtered as `<MISSING>`.

```bash
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet \
  --group-by direction,pvsra_classification,h1_direction,h4_direction,d1_direction \
  --where direction=BUY --where pvsra_classification=CLIMAX \
  --segment-by year --min-samples 30 --horizons 1,4,8,16,32 \
  --output data/research/analysis/buy_climax_by_year.csv
```

For a descriptive stability report, select one cohort with repeated filters
and segment it by year:

```bash
.venv/bin/python -m src.main research-analyze data/research/XAUUSDc_M15_events.parquet \
  --where direction=BUY --where pvsra_classification=CLIMAX \
  --where h4_structural_alignment=ALIGNED --segment-by year --horizons 16
```

`--segment-by` accepts `year`, `quarter`, or `month`, based on the event
knowledge timestamp in UTC. Only observed combinations are shown.
`--min-samples` hides rows from the report/export; it does not alter the
Parquet source. An export path ending in `.csv` or `.parquet` writes explicit
cohort columns and a deterministic `.meta.json` sidecar containing the source
path and SHA256, report, grouping fields, filters, segmentation, horizons, and
minimum sample count. `data/research/analysis/` is ignored by Git. Overview
also prints the full filtered
event count, UTC date range, BUY/SELL and event-type counts, PVSRA counts,
and outcome availability.

Each output row describes one cohort and one saved forward horizon. `n` is
the number of events in the cohort; `available_n` counts events whose saved
outcome exists at that horizon. Means, medians, quartiles, positive/negative/
zero counts, and positive percentage use only available observations.
Directional returns and excursions are dimensionless fractions, while
`positive_pct` is 0–100. Missing outcome summaries are null. The reported
`median_mfe_minus_median_mae` is a descriptive difference of medians.
These are historical descriptions, without execution or transaction costs.
