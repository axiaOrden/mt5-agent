"""Offline, reproducible VCZ lifecycle diagnostic; no market formulas here.

Run from the project root:
    .venv/bin/python -m scripts.inspect_vcz_lifecycle
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from statistics import median

import pandas as pd

from src.research.acquisition import ResearchHistoryStore
from src.research.vcz import VCZSide, VCZStatus, _update
from src.research.vcz_history import replay_native_vcz


# Chosen from chronological H4 geometry categories, never from forward returns.
EXAMPLES = (
    ("2024-04-10 20:00", "upward travel; both copies recovered within three update bars"),
    ("2024-04-11 12:00", "new PVSRA while an older BELOW copy is shrinking"),
    ("2024-04-12 00:00", "downward travel after the source"),
    ("2024-04-12 08:00", "both copies recovered on the first update bar"),
    ("2024-04-12 16:00", "sideways overlap; both copies initially shrink"),
    ("2024-05-03 12:00", "oldest surviving H4 copy"),
    ("2024-06-26 12:00", "second-oldest surviving H4 copy"),
    ("2024-08-22 12:00", "earliest surviving fraction below 0.10"),
    ("2024-09-06 16:00", "second-earliest surviving fraction below 0.10"),
    ("2026-01-29 04:00", "earliest surviving ABOVE copy"),
    ("2026-01-30 00:00", "earliest ABOVE residual below 0.10"),
)


def _stamp(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def _range(zone) -> str:
    return f"[{zone.current_bottom:.3f}, {zone.current_top:.3f}]" if zone else "—"


def _seed(zone):
    return replace(zone, current_bottom=zone.original_bottom,
                   current_top=zone.original_top, last_updated_at=None,
                   fully_recovered_at=None, fully_recovered_bar_index=None,
                   display_evicted_at=None, partial_update_count=0)


def _mechanic(before, after, row, side):
    if before is None or before.status == VCZStatus.FULLY_RECOVERED:
        return "already fully recovered"
    if after.status == VCZStatus.FULLY_RECOVERED:
        if side == VCZSide.ABOVE:
            cause = (f"close {row.close:.3f} ≥ top" if row.close >= before.current_top
                     else f"high {row.high:.3f} ≥ top")
        else:
            cause = (f"close {row.close:.3f} ≤ bottom" if row.close <= before.current_bottom
                     else f"low {row.low:.3f} ≤ bottom")
        return "fully recovered: " + cause
    if side == VCZSide.ABOVE and after.current_bottom != before.current_bottom:
        return f"shrink: high {row.high:.3f} inside → bottom {after.current_bottom:.3f}"
    if side == VCZSide.BELOW and after.current_top != before.current_top:
        return f"shrink: low {row.low:.3f} inside → top {after.current_top:.3f}"
    return "unchanged"


def _trace_pair(bars: pd.DataFrame, pair: dict, source_times: set) -> tuple[list[dict], list[dict]]:
    """Trace selected copies by calling V1's own update branch, not reimplementing it."""
    above = pair[VCZSide.ABOVE]
    below = pair[VCZSide.BELOW]
    states = {VCZSide.BELOW: _seed(below), VCZSide.ABOVE: _seed(above)}
    events = []
    for i in range(above.created_bar_index, len(bars)):
        row = bars.iloc[i]
        at = (pd.Timestamp(row.time) + pd.Timedelta(hours=4)).to_pydatetime()
        item = {"bar": i - (above.created_bar_index - 1), "index": i,
                "time": _stamp(row.time), "open": float(row.open),
                "high": float(row.high), "low": float(row.low),
                "close": float(row.close),
                "new_pvsra_source": pd.Timestamp(row.time).to_pydatetime() in source_times}
        for side in (VCZSide.BELOW, VCZSide.ABOVE):
            before = states[side]
            after = (_update(before, side, float(row.close), float(row.high),
                             float(row.low), at, i)
                     if before.status == VCZStatus.REMAINING else before)
            item[side.value] = {"before": _range(before), "after": _range(after),
                                "action": _mechanic(before, after, row, side)}
            states[side] = after
        events.append(item)
        if all(state.status == VCZStatus.FULLY_RECOVERED for state in states.values()):
            break
    # The selected-zone trace must reproduce its record in the unbounded V1 replay.
    for side, original in ((VCZSide.BELOW, below), (VCZSide.ABOVE, above)):
        traced = states[side]
        assert (traced.current_bottom, traced.current_top, traced.status,
                traced.partial_update_count, traced.fully_recovered_at) == (
                original.current_bottom, original.current_top, original.status,
                original.partial_update_count, original.fully_recovered_at)
    # Show the first ten update bars and every subsequent actual change. Quiet
    # intervals are summarized rather than printing thousands of identical rows.
    shown = [e for e in events if e["bar"] <= 10 or any(
        e[side.value]["action"] not in ("unchanged", "already fully recovered")
        for side in (VCZSide.BELOW, VCZSide.ABOVE))]
    return events, shown


def _status_counts(zones):
    return (sum(z.status == VCZStatus.FULLY_RECOVERED for z in zones),
            sum(z.status == VCZStatus.REMAINING for z in zones))


def _median(values):
    values = [value for value in values if value is not None]
    return f"{median(values):.3f}" if values else "—"


def _summary_section(replay):
    lines = ["## H4 descriptive counts", "",
             "Recovery timing uses disjoint bins: first update bar (source +1), second (source +2), "
             "third–fourth, fifth–eighth, later, and remaining at the stored-history end. "
             "A recovery on the creation/update bar has `bars_until_recovery=0` in V1.", "",
             "| Selector | Zones | Fully recovered | Remaining | Median recovery bars after creation | Median remaining fraction | First | Second | Third–fourth | Fifth–eighth | Later | Still remaining |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for side in (VCZSide.BELOW, VCZSide.ABOVE):
        zones = [z for z in replay.zones if z.side == side]
        recovered, remaining = _status_counts(zones)
        timing = Counter()
        for z in zones:
            n = z.bars_until_recovery
            timing["still"] += int(n is None)
            if n is None:
                continue
            timing["first" if n == 0 else "second" if n == 1 else
                   "3-4" if n <= 3 else "5-8" if n <= 7 else "later"] += 1
        lines.append(f"| {side.value} (direction={0 if side == VCZSide.BELOW else 1}) | {len(zones)} | {recovered} | {remaining} | "
                     f"{_median(z.bars_until_recovery for z in zones if z.status == VCZStatus.FULLY_RECOVERED)} | "
                     f"{_median(z.remaining_fraction for z in zones if z.status == VCZStatus.REMAINING)} | "
                     f"{timing['first']} | {timing['second']} | {timing['3-4']} | {timing['5-8']} | "
                     f"{timing['later']} | {timing['still']} |")
    lines.extend(["", "### Source candle direction", "",
                  "| Source direction | Selector | Zones | Fully recovered | Remaining |",
                  "|---|---|---:|---:|---:|"])
    for direction in ("BULLISH", "BEARISH"):
        for side in (VCZSide.BELOW, VCZSide.ABOVE):
            zones = [z for z in replay.zones if z.pvsra_candle_direction.value == direction and z.side == side]
            recovered, remaining = _status_counts(zones)
            lines.append(f"| {direction} | {side.value} | {len(zones)} | {recovered} | {remaining} |")
    lines.extend(["", "### PVSRA classification", "",
                  "| Source class | Selector | Zones | Fully recovered | Remaining | Median recovery bars after creation |",
                  "|---|---|---:|---:|---:|---:|"])
    for classification in ("ABOVE_AVERAGE", "CLIMAX"):
        for side in (VCZSide.BELOW, VCZSide.ABOVE):
            zones = [z for z in replay.zones if z.pvsra_classification.value == classification and z.side == side]
            recovered, remaining = _status_counts(zones)
            lines.append(f"| {classification} | {side.value} | {len(zones)} | {recovered} | {remaining} | "
                         f"{_median(z.bars_until_recovery for z in zones if z.status == VCZStatus.FULLY_RECOVERED)} |")
    return lines


def _examples_section(bars, replay):
    pairs = defaultdict(dict)
    for zone in replay.zones:
        pairs[zone.source_bar_open_time][zone.side] = zone
    source_times = set(pairs)
    lines = ["## Eleven H4 lifecycle examples", "",
             "Selection used chronological source-pair scans, never forward return or profit. "
             "Upward/downward travel means that within the next four H4 bars, a high exceeded "
             "source high + source height or a low fell below source low − source height; "
             "the listed cases are the first such sources from April 2024 onward. "
             "The dual-immediate case is the first post-April-2024 source whose two copies "
             "recovered on bar +1. The interaction case is the first such source whose next "
             "qualifying PVSRA bar changes an older copy. The sideways case is the first "
             "post-April-2024 source with the next bar strictly inside its high–low range "
             "and both copies lasting at least four update bars. The remaining cases are "
             "the two oldest survivors, first two sub-10% residuals, first surviving ABOVE "
             "copy, and first sub-10% ABOVE residual. Source timestamps are fixed in the "
             "diagnostic script for reproducibility.", ""]
    lines.extend(["| Source UTC | Class / source direction | Original height | BELOW outcome | ABOVE outcome | First fully recovered |",
                  "|---|---|---:|---|---|---|"])
    for stamp, _ in EXAMPLES:
        pair = pairs[pd.Timestamp(stamp, tz="UTC").to_pydatetime()]
        below, above = pair[VCZSide.BELOW], pair[VCZSide.ABOVE]
        def outcome(zone):
            return (f"recovered after {zone.bars_until_recovery} creation bars"
                    if zone.status == VCZStatus.FULLY_RECOVERED
                    else f"remaining fraction {zone.remaining_fraction:.3f}")
        delays = [(zone.bars_until_recovery, zone.side.value)
                  for zone in (below, above) if zone.bars_until_recovery is not None]
        first = ("both together" if len(delays) == 2 and delays[0][0] == delays[1][0]
                 else min(delays)[1] if delays else "neither")
        lines.append(f"| {stamp} | {below.pvsra_classification.value} / {below.pvsra_candle_direction.value} | "
                     f"{below.original_height:.3f} | {outcome(below)} | {outcome(above)} | {first} |")
    lines.append("")
    first_actions = Counter()
    for number, (stamp, reason) in enumerate(EXAMPLES, 1):
        source = pd.Timestamp(stamp, tz="UTC").to_pydatetime()
        pair = pairs[source]
        below, above = pair[VCZSide.BELOW], pair[VCZSide.ABOVE]
        row = bars.iloc[below.created_bar_index - 1]
        events, shown = _trace_pair(bars, pair, source_times)
        first_actions.update(events[0][side.value]["action"].split(":")[0]
                             for side in (VCZSide.BELOW, VCZSide.ABOVE))
        lines.extend([
            f"### {number}. {_stamp(source)} UTC — {reason}", "",
            f"SOURCE XAUUSDc H4: open `{_stamp(source)} UTC`, close/knowledge `{_stamp(below.source_bar_close_time)} UTC`; "
            f"{below.pvsra_classification.value}, candle {below.pvsra_candle_direction.value}, flag `{below.pvsra_flag:+d}`. "
            f"OHLC `{row.open:.3f}/{row.high:.3f}/{row.low:.3f}/{row.close:.3f}`; "
            f"original VCZ `[{below.original_bottom:.3f}, {below.original_top:.3f}]`. "
            f"BELOW direction=0 ID `{below.zone_id}`; ABOVE direction=1 ID `{above.zone_id}`.", "",
            "On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.", "",
            "| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |",
            "|---:|---|---|---|---|",
        ])
        previous_index = below.created_bar_index - 1
        for e in shown:
            if e["index"] > previous_index + 1:
                lines.append(f"| … | — | {e['index'] - previous_index - 1} unchanged bar(s) omitted | — | — |")
            flag = " **new PVSRA source**" if e["new_pvsra_source"] else ""
            lo, hi = e["BELOW"], e["ABOVE"]
            lines.append(f"| +{e['bar']} | {e['time']}{flag} | "
                         f"{e['open']:.3f}/{e['high']:.3f}/{e['low']:.3f}/{e['close']:.3f} | "
                         f"{lo['before']} → {lo['after']}; {lo['action']} | "
                         f"{hi['before']} → {hi['after']}; {hi['action']} |")
            previous_index = e["index"]
        if events[-1]["index"] > previous_index:
            lines.append(f"| … | — | {events[-1]['index'] - previous_index} final unchanged bar(s) omitted | — | — |")
        lines.append("")
        lines.append(f"FINAL at stored-history end: BELOW {below.status.value} {_range(below)} "
                     f"(updates={below.partial_update_count}, recovery={below.bars_until_recovery}); "
                     f"ABOVE {above.status.value} {_range(above)} "
                     f"(updates={above.partial_update_count}, recovery={above.bars_until_recovery}).")
        if below.status == VCZStatus.REMAINING or above.status == VCZStatus.REMAINING:
            lines.append(f"Surviving copy age: {replay.candles_processed - 1 - below.created_bar_index} H4 bars "
                         f"since creation; remaining fractions: BELOW "
                         f"{_median([below.remaining_fraction]) if below.status == VCZStatus.REMAINING else '—'}, "
                         f"ABOVE {_median([above.remaining_fraction]) if above.status == VCZStatus.REMAINING else '—'}.")
        if stamp == "2024-04-11 12:00":
            child = pairs[pd.Timestamp("2024-04-11 16:00", tz="UTC").to_pydatetime()]
            lines.append("The 16:00 bar is itself qualifying PVSRA and shrinks the older BELOW copy. "
                         "It creates a separate pair from its own range when the 20:00 bar is processed: "
                         f"new BELOW `{child[VCZSide.BELOW].zone_id}`, "
                         f"new ABOVE `{child[VCZSide.ABOVE].zone_id}`. No zones are merged.")
        lines.append("")
    lines.extend(["### Immediate next-bar outcomes in the selected copies", "",
                  "The 11 sources produce 22 copies. Their first completed update bar produced: " +
                  ", ".join(f"{key}={value}" for key, value in sorted(first_actions.items())) + ".", ""])
    return lines


def build_report(history_dir: Path, symbol: str, compare_timeframes: bool = True) -> str:
    store = ResearchHistoryStore(history_dir)
    daily = store.load(symbol, "D1")
    bars = store.load(symbol, "H4")
    if bars.empty or daily.empty:
        raise ValueError(f"saved {symbol} H4 and D1 history required")
    replay = replay_native_vcz(bars, daily, symbol=symbol, timeframe="H4")
    h4_hash = sha256(store.path_for(symbol, "H4").read_bytes()).hexdigest()
    lines = ["# VCZ lifecycle diagnostic — XAUUSDc H4", "",
             f"Git base: `1c5d5bc`. Input: saved `{symbol}` H4 candles (`{len(bars):,}` rows); "
             f"H4 Parquet SHA256 `{h4_hash}`. No MT5 or Wine access.", "",
             "## Scope and Pine mechanics", "",
             "**Observed:** existing native H4 PVSRA results and the existing V1 VCZ engine produce "
             "two independent copies of each qualifying source range. Pine's fixed "
             "`direction=0` BELOW selector lowers the top when a later low enters, and "
             "`direction=1` ABOVE selector raises the bottom when a later high enters. "
             "A low at/below bottom or high at/above top fully recovers the respective copy. "
             "The qualifying source is the previous candle, and the next candle can update "
             "the newly created copies immediately. NORMAL candles update them too. "
             "This report uses full-history research replay with no display-array cap.", "",
             "**Mechanical interpretation:** a surviving fragment exists because later completed "
             "bars have not met that copy's terminal Pine condition. This does not establish "
             "what orders, participants, or intentions were present there.", "",
             "**Market hypothesis:** ideas about orders, stops, continuation, or reversal are "
             "untested and are not evaluated here.", ""]
    lines.extend(_summary_section(replay))
    lines.append("")
    lines.extend(_examples_section(bars, replay))
    if compare_timeframes:
        lines.extend(["## Native-timeframe comparison", "",
                      "Each row uses its own candles and existing PVSRA; no M15 aggregation.", "",
                      "| Timeframe | Zones | BELOW remaining | ABOVE remaining | BELOW median recovered bars | ABOVE median recovered bars | BELOW median remaining fraction | ABOVE median remaining fraction |",
                      "|---|---:|---:|---:|---:|---:|---:|---:|"])
        for timeframe in ("M15", "H1", "H4", "D1"):
            item = replay if timeframe == "H4" else replay_native_vcz(
                store.load(symbol, timeframe), daily, symbol=symbol, timeframe=timeframe)
            by_side = {side: [z for z in item.zones if z.side == side]
                       for side in (VCZSide.BELOW, VCZSide.ABOVE)}
            below, above = by_side[VCZSide.BELOW], by_side[VCZSide.ABOVE]
            lines.append(f"| {timeframe} | {len(item.zones)} | "
                         f"{sum(z.status == VCZStatus.REMAINING for z in below)} | "
                         f"{sum(z.status == VCZStatus.REMAINING for z in above)} | "
                         f"{_median(z.bars_until_recovery for z in below if z.status == VCZStatus.FULLY_RECOVERED)} | "
                         f"{_median(z.bars_until_recovery for z in above if z.status == VCZStatus.FULLY_RECOVERED)} | "
                         f"{_median(z.remaining_fraction for z in below if z.status == VCZStatus.REMAINING)} | "
                         f"{_median(z.remaining_fraction for z in above if z.status == VCZStatus.REMAINING)} |")
        lines.append("")
    lines.extend(["## Observations and open questions", "",
                  "- **Upward travel:** the 2024-04-10 20:00 source's ABOVE copy recovered on bar +1 "
                  "when the next close exceeded its top; the BELOW copy first shrank and recovered "
                  "on bar +3 when a later low crossed its bottom. Direction=1 and direction=0 are "
                  "fixed price-coverage branches, not forecasts from the source's bullish candle.",
                  "- **Downward travel:** the 2024-04-12 00:00 source's BELOW copy shrank twice "
                  "and recovered when bar +4 closed below its bottom. This source was also bullish. "
                  "The 2024-04-12 08:00 bearish source had both copies recovered on bar +1 because "
                  "that bar's range spanned both original boundaries.",
                  "- **Sideways overlap:** the 2024-04-12 16:00 CLIMAX source's first next bar "
                  "lay inside its wide original range; its low lowered the BELOW top and its high "
                  "raised the ABOVE bottom. These copies remained distinct and recovered on later bars.",
                  "- **Source direction is independent:** H4 retains 60 BELOW copies sourced from "
                  "bullish candles and 21 ABOVE copies sourced from bearish candles. The bearish "
                  "2026-01-30 00:00 source leaves an ABOVE fragment of about 9.4% at the history end.",
                  "- **Long-lived fragments:** BELOW copies from 2024-05-03 and 2024-06-26 "
                  "remain after 3,813 and 3,577 H4 bars, respectively. Their latest bounds are "
                  "shown in examples 6–7; thousands of later bars did not satisfy `low <= bottom`. "
                  "Small BELOW remnants from 2024-08-22 and 2024-09-06 retain about 3.1% and "
                  "2.1% of original height after repeated low-based shrinking. Fragment size is "
                  "descriptive geometry only.",
                  "- **New activity during recovery:** the qualifying 2024-04-11 16:00 candle "
                  "shrunk an older BELOW copy. On the next bar, its own independent pair was "
                  "created and processed. No zone merge occurred.",
                  "- ABOVE_AVERAGE and CLIMAX follow the same recovery branches after creation. "
                  "Their cross-tab counts and median lifetimes differ in this history, but no "
                  "class-specific recovery rule or predictive conclusion follows.", "",
                  "Open research questions: how should movement away be defined before an encounter, "
                  "which completed-bar information should define a return, and how should overlapping "
                  "remaining fragments be presented without implying priority? No AOI, revisit, "
                  "reaction, entry, or trade semantics are defined by this study.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSDc")
    parser.add_argument("--history-dir", type=Path, default=Path("data/research/history"))
    parser.add_argument("--output", type=Path, default=Path("docs/vcz-lifecycle-study.md"))
    parser.add_argument("--h4-only", action="store_true", help="skip optional other-timeframe comparison")
    args = parser.parse_args()
    report = build_report(args.history_dir, args.symbol, compare_timeframes=not args.h4_only)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
