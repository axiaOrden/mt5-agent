"""Descriptive statistics over replay records; no rankings or recommendations."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean, median

from .models import HorizonStatistics, ReplayEvent, StatisticsGroup


def summarize(
    events: tuple[ReplayEvent, ...],
    horizons: tuple[int, ...],
    *,
    group_by: str | None = None,
) -> tuple[StatisticsGroup, ...]:
    grouped = defaultdict(list)
    for event in events:
        key = "ALL" if group_by is None else _dimension(event, group_by)
        grouped[str(key)].append(event)
    return tuple(
        StatisticsGroup(key, len(items), _horizon_statistics(items, horizons))
        for key, items in sorted(grouped.items())
    )


def _horizon_statistics(events, horizons):
    rows = []
    for horizon in horizons:
        outcomes = [
            outcome for event in events for outcome in event.outcomes
            if outcome.horizon == horizon and outcome.available
        ]
        directional = [item.directional_return for item in outcomes]
        mfes = [item.mfe for item in outcomes]
        maes = [item.mae for item in outcomes]
        rows.append(HorizonStatistics(
            horizon=horizon,
            sample_count=len(outcomes),
            mean_directional_return=mean(directional) if directional else None,
            median_directional_return=median(directional) if directional else None,
            median_mfe=median(mfes) if mfes else None,
            median_mae=median(maes) if maes else None,
        ))
    return tuple(rows)


def _dimension(event: ReplayEvent, name: str):
    if name == "event_type":
        return event.event_type.value
    if name == "label":
        return event.label or "NONE"
    if name == "event_direction":
        return event.event_direction.value
    if name == "pvsra_classification":
        return event.event_pvsra.classification.value if event.event_pvsra else "UNAVAILABLE"
    if name == "pvsra_candle_direction":
        return event.event_pvsra.candle_direction.value if event.event_pvsra else "UNAVAILABLE"
    if name in ("market_direction", "market_condition"):
        context = event.context_for(event.event_timeframe)
        return getattr(context, name) if context else "UNAVAILABLE"
    parts = name.split("_", 1)
    if len(parts) == 2 and parts[0].upper() in ("M15", "H1", "H4", "D1"):
        context = event.context_for(parts[0].upper())
        if context is None:
            return "UNAVAILABLE"
        field = parts[1]
        aliases = {
            "direction": "market_direction", "condition": "market_condition",
            "structural_alignment": "structural_alignment",
            "cloudgazer_alignment": "cloudgazer_alignment",
            "cloudgazer_state": "cloudgazer_state",
        }
        if field not in aliases:
            raise ValueError(f"Unsupported grouping dimension: {name}")
        value = getattr(context, aliases[field])
        return value.value if hasattr(value, "value") else value or "UNAVAILABLE"
    raise ValueError(f"Unsupported grouping dimension: {name}")
