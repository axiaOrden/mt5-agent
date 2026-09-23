"""Single-core Phase 1.9 replay benchmark (no provider calls or writes)."""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from time import perf_counter

import pandas as pd

from src.mt5.closure import bar_duration
from src.research.acquisition import ResearchHistoryStore, utc_date
from src.research.replay import replay_history
import src.research.context_index as indexed_module
import src.context.engine as context_module


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", help="broker symbol, e.g. XAUUSDc")
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--timeframe", choices=("M15", "H1", "H4", "D1"), default="M15")
    parser.add_argument("--warmup-days", type=int, default=180)
    parser.add_argument("--history-dir", type=Path, default=Path("data/research/history"))
    args = parser.parse_args()
    start = utc_date(args.from_date)
    end = utc_date(args.to_date)
    if end <= start or args.warmup_days < 0:
        parser.error("end must follow start and warmup-days must be nonnegative")

    store = ResearchHistoryStore(args.history_dir)
    timeframes = ("M15", "H1", "H4", "D1")
    selected = timeframes[timeframes.index(args.timeframe):]
    warmup_start = start - timedelta(days=args.warmup_days)
    histories = {}
    for timeframe in selected:
        frame = store.load(args.symbol, timeframe)
        if frame.empty:
            parser.error(f"missing research history: {args.symbol} {timeframe}")
        # Include an opening bar before warmup when it overlaps the boundary.
        lower = pd.Timestamp(warmup_start - bar_duration(timeframe))
        histories[timeframe] = frame[(frame["time"] >= lower) &
                                    (frame["time"] < pd.Timestamp(end))].reset_index(drop=True)

    calls = []
    original_indexed = indexed_module.replay_cloudgazer
    original_live = context_module.replay_cloudgazer

    def counted(*call_args, **call_kwargs):
        calls.append(call_args[2])
        return original_indexed(*call_args, **call_kwargs)

    indexed_module.replay_cloudgazer = counted
    context_module.replay_cloudgazer = counted
    try:
        begin = perf_counter()
        result = replay_history(histories, args.symbol, args.timeframe,
                                report_from=start, report_to=end)
        elapsed = perf_counter() - begin
    finally:
        indexed_module.replay_cloudgazer = original_indexed
        context_module.replay_cloudgazer = original_live

    print(json.dumps({
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "from_inclusive": start.isoformat(),
        "to_exclusive": end.isoformat(),
        "warmup_days": args.warmup_days,
        "candles": result.closed_candles,
        "state_changing_events": len(result.events),
        "runtime_seconds": round(elapsed, 3),
        "replay_cloudgazer_invocations": len(calls),
        "calls_by_timeframe": {tf: calls.count(tf) for tf in selected},
    }, indent=2))


if __name__ == "__main__":
    main()
