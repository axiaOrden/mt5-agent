# Deep research history

`research-sync` is an explicit read-only operation. It stores broker candles in
`data/research/history/<broker-symbol>/<timeframe>.parquet`, separate from the
normal lightweight history cache. For example:

```bash
.venv/bin/python -m src.main research-sync XAUUSD --from 2026-06-01 --to 2026-09-22
.venv/bin/python -m src.main replay XAUUSD --timeframe M15 --research-history --from 2026-06-01 --to 2026-09-22
```

Dates are UTC midnight. `--from` is inclusive; `--to` is exclusive. The default
180 calendar day warmup is acquired before `--from` for Ichimoku, PVSRA,
multi-timeframe context, and Cloudgazer state initialization. It is
configurable with `--warmup-days`; a state machine has no finite mathematical
warmup guarantee. Replay computes from all stored warmup candles, then filters
exported events by **event knowledge time**. Future outcomes still use later
stored candles. A missing warmup edge is reported; broker history is never
fabricated.

Requests use 14 day `[start, end)` windows by default, with a one-candle
overlap. The remote bridge also accepts an exclusive `to` timestamp. When a
range is new or contains a large gap, acquisition first asks MT5 for bounded
calendar-year windows. This prompts MT5 to load older terminal history; valid
priming candles are merged and verified with the same closure and OHLC rules.
Small chunks then repair missing coverage. An empty short chunk in a large
gap triggers a bounded year re-prime and one retry. Persistent empties are
reported. Existing interior coverage is reused only when it has no suspicious
gap; uncovered prefix and tail chunks are requested.
`--force-refresh` requests every chunk again. Failed chunks leave the last
valid Parquet dataset intact. Each successful chunk is normalized, checked,
written to a temporary Parquet file, read back, then atomically replaced.
Identical timestamps are deduplicated. If values conflict, the latest broker
retrieval wins and the revision count is reported. `--force-refresh` can reveal
broker revisions; it does not keep earlier versions.

Validation rejects null or nonfinite OHLC/tick volume, inconsistent OHLC,
negative volume or spread, invalid intraday minute/second precision, and malformed
columns. D1 open timestamps retain their actual UTC hour even if broker
session times change. A gap report identifies discontinuities without filling
market closures or holidays. Interior gaps longer than seven calendar days
are classified as suspicious. The boundary checks are separate from
`continuously usable`, which requires both requested boundaries and no
suspicious interior gap. Research replay fails before export/statistics if its
requested range crosses such a gap; ordinary weekends remain valid. Coverage
reports include actual endpoints,
warmup/end reach, empty broker responses, D1 open-hour distribution, and
a SHA256 hash of normalized candle content. `latest_acquisition.json` records
the request, broker symbol, counts, timestamps, warmup, and fingerprints.

The bridge and provider remain read-only. The existing `replay` command keeps
its ordinary operational-history behavior unless `--research-history` is
explicitly selected.
