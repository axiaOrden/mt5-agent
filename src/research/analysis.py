"""Offline, descriptive cohort analysis of Phase 1.9 replay exports.

All outcome values are read from the artifact. Nothing here replays signals or
queries a broker. A row in the result represents one observed cohort/horizon.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


BASE_FIELDS = ("symbol", "event_timeframe", "event_knowledge_time", "event_type",
               "event_direction", "label", "previous_state", "new_state",
               "pvsra_classification")
CONTEXT_SUFFIXES = ("role", "direction", "condition", "cloudgazer_state",
                    "structural_alignment", "cloudgazer_alignment")
PVSRA_FIELDS = ("pvsra_direction", "pvsra_volume_source")
DEFAULT_HORIZONS = (1, 4, 8, 16, 32)
REPORTS = ("overview", "pvsra", "direction-pvsra", "higher-timeframe",
           "structural-alignment", "cloudgazer-alignment")
ALIASES = {"direction": "label"}  # CLI examples use BUY/SELL, the persisted label.
OUTCOME_SUFFIXES = ("available", "directional_return", "mfe", "mae")
MISSING_CATEGORY = "<MISSING>"


def load_replay(path: str | Path) -> pd.DataFrame:
    """Read and validate the stable fields needed for cohort analysis."""
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError, ImportError) as exc:
        raise ValueError(f"Cannot read replay Parquet {path}: {exc}") from exc
    required = set(BASE_FIELDS)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Incompatible replay dataset; missing fields: {', '.join(missing)}")
    incomplete = sorted(int(match.group(1)) for col in frame.columns
                        if (match := re.fullmatch(r"forward_(\d+)_available", col))
                        and any(f"forward_{match.group(1)}_{suffix}" not in frame
                                for suffix in OUTCOME_SUFFIXES))
    if incomplete:
        raise ValueError(f"Incompatible replay dataset; incomplete outcome horizon(s): {', '.join(map(str, incomplete))}")
    horizons = available_horizons(frame)
    if not horizons:
        raise ValueError("Incompatible replay dataset; no complete forward outcome horizons")
    for horizon in horizons:
        prefix = f"forward_{horizon}_"
        for suffix in OUTCOME_SUFFIXES[1:]:
            column = prefix + suffix
            if not pd.api.types.is_numeric_dtype(frame[column]):
                raise ValueError(f"Incompatible replay dataset; {column} must be numeric")
        column = prefix + "available"
        if not pd.api.types.is_bool_dtype(frame[column]):
            raise ValueError(f"Incompatible replay dataset; {column} must be boolean")
        valid = frame[column]
        if frame.loc[valid, [prefix + s for s in OUTCOME_SUFFIXES[1:]]].isna().any().any():
            raise ValueError(f"Incompatible replay dataset; available horizon {horizon} has missing outcomes")
    try:
        frame["event_knowledge_time"] = pd.to_datetime(frame["event_knowledge_time"], utc=True, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("Incompatible replay dataset; invalid event_knowledge_time") from exc
    if frame["event_knowledge_time"].isna().any():
        raise ValueError("Incompatible replay dataset; null event_knowledge_time")
    return frame


def available_horizons(frame: pd.DataFrame) -> tuple[int, ...]:
    candidates = sorted(int(match.group(1)) for col in frame.columns
                        if (match := re.fullmatch(r"forward_(\d+)_available", col)))
    return tuple(h for h in candidates if all(f"forward_{h}_{s}" in frame for s in OUTCOME_SUFFIXES))


def dimensions(frame: pd.DataFrame) -> tuple[str, ...]:
    allowed = set(BASE_FIELDS) | set(PVSRA_FIELDS)
    allowed.discard("event_knowledge_time")
    allowed.update(f"{tf}_{suffix}" for tf in ("m15", "h1", "h4", "d1")
                   for suffix in CONTEXT_SUFFIXES)
    return tuple(sorted(allowed & set(frame.columns)))


def resolve_fields(frame: pd.DataFrame, spec: str | None) -> tuple[str, ...]:
    if not spec:
        return ()
    names = tuple(ALIASES.get(name.strip(), name.strip()) for name in spec.split(","))
    if not all(names) or len(names) != len(set(names)):
        raise ValueError("--group-by requires unique, nonempty field names")
    invalid = sorted(set(names) - set(dimensions(frame)))
    if invalid:
        raise ValueError(f"Unknown grouping field(s): {', '.join(invalid)}; use --list-fields")
    return names


def filter_events(frame: pd.DataFrame, filters: list[str]) -> pd.DataFrame:
    result = frame
    for expression in filters:
        if expression.count("=") != 1:
            raise ValueError(f"Malformed filter {expression!r}; expected FIELD=VALUE")
        raw_field, value = (part.strip() for part in expression.split("=", 1))
        field = ALIASES.get(raw_field, raw_field)
        if field not in dimensions(frame):
            raise ValueError(f"Unknown filter field {raw_field!r}; use --list-fields")
        if not value:
            raise ValueError(f"Malformed filter {expression!r}; value is empty")
        choices = set(frame[field].dropna().astype(str))
        if frame[field].isna().any():
            choices.add(MISSING_CATEGORY)
        if value not in choices:
            raise ValueError(f"Invalid {raw_field} value {value!r}; available: {', '.join(sorted(choices))}")
        result = result.loc[result[field].fillna(MISSING_CATEGORY).astype(str).eq(value)]
    return result


def segment_events(frame: pd.DataFrame, period: str | None) -> pd.DataFrame:
    if period is None:
        return frame
    if period not in ("year", "quarter", "month"):
        raise ValueError("--segment-by must be year, quarter, or month")
    result = frame.copy()
    timestamp = result["event_knowledge_time"].dt
    if period == "year":
        result["period"] = timestamp.strftime("%Y")
    elif period == "month":
        result["period"] = timestamp.strftime("%Y-%m")
    else:
        result["period"] = timestamp.year.astype(str) + "-Q" + timestamp.quarter.astype(str)
    return result


def _cohorts(frame: pd.DataFrame, fields: tuple[str, ...]):
    if not fields:
        yield (), frame
        return
    # Null and the persisted UNAVAILABLE state are distinct observed cohorts.
    keys = frame.loc[:, list(fields)].fillna(MISSING_CATEGORY)
    for key, positions in keys.groupby(list(fields), sort=True).indices.items():
        yield key if isinstance(key, tuple) else (key,), frame.iloc[positions]


def cohort_statistics(frame: pd.DataFrame, fields: tuple[str, ...] = (),
                      horizons: tuple[int, ...] | None = None,
                      min_samples: int = 1) -> pd.DataFrame:
    """Summarize observed cohorts. N is all events; available_n is outcome rows."""
    if min_samples < 1:
        raise ValueError("--min-samples must be positive")
    horizons = horizons or available_horizons(frame)
    unavailable = sorted(set(horizons) - set(available_horizons(frame)))
    if unavailable:
        raise ValueError(f"Unavailable outcome horizon(s): {', '.join(map(str, unavailable))}")
    rows = []
    for key, group in _cohorts(frame, fields):
        n = len(group)
        if n < min_samples:
            continue
        for horizon in horizons:
            prefix = f"forward_{horizon}_"
            observed = group.loc[group[prefix + "available"]]
            directional = observed[prefix + "directional_return"]
            mfe = observed[prefix + "mfe"]
            mae = observed[prefix + "mae"]
            count = len(observed)
            median_mfe = mfe.median()
            median_mae = mae.median()
            rows.append(dict(zip(fields, key)) | {
                "horizon": horizon, "n": n, "available_n": count,
                "mean_directional_return": directional.mean(),
                "median_directional_return": directional.median(),
                "p25_directional_return": directional.quantile(.25),
                "p75_directional_return": directional.quantile(.75),
                "positive_count": int((directional > 0).sum()),
                "negative_count": int((directional < 0).sum()),
                "zero_count": int((directional == 0).sum()),
                "positive_pct": 100 * (directional > 0).sum() / count if count else float("nan"),
                "mean_mfe": mfe.mean(), "median_mfe": median_mfe,
                "mean_mae": mae.mean(), "median_mae": median_mae,
                "median_mfe_minus_median_mae": median_mfe - median_mae,
            })
    return pd.DataFrame(rows, columns=[*fields, "horizon", "n", "available_n",
                                       "mean_directional_return", "median_directional_return",
                                       "p25_directional_return", "p75_directional_return",
                                       "positive_count", "negative_count", "zero_count", "positive_pct",
                                       "mean_mfe", "median_mfe", "mean_mae", "median_mae",
                                       "median_mfe_minus_median_mae"])


def report_groups(frame: pd.DataFrame, report: str) -> list[tuple[str, tuple[str, ...]]]:
    if report == "overview":
        return [("all events", ())]
    if report == "pvsra":
        return [("PVSRA", ("pvsra_classification",))]
    if report == "direction-pvsra":
        return [("direction × PVSRA", ("label", "pvsra_classification"))]
    if report == "higher-timeframe":
        contexts = [f"{tf}_direction" for tf in ("h1", "h4", "d1") if f"{tf}_direction" in frame]
        return [(field, (field,)) for field in contexts] + ([('combined directions', tuple(contexts))] if contexts else [])
    if report in ("structural-alignment", "cloudgazer-alignment"):
        suffix = report.replace("-", "_")
        return [(field, (field,)) for tf in ("m15", "h1", "h4", "d1")
                if (field := f"{tf}_{suffix}") in frame]
    raise ValueError(f"Unknown report {report!r}")


def overview(frame: pd.DataFrame, horizons: tuple[int, ...]) -> str:
    lines = [f"Events: {len(frame):,}"]
    if len(frame):
        lines.append(f"Knowledge time (UTC): {frame.event_knowledge_time.min()} → {frame.event_knowledge_time.max()}")
    for field in ("label", "event_type", "pvsra_classification"):
        lines.append(f"{field}: " + ", ".join(f"{key}={value:,}" for key, value in
                                              frame[field].fillna(MISSING_CATEGORY).value_counts().sort_index().items()))
    lines.append("Outcome availability: " + ", ".join(
        f"H{h}={int(frame[f'forward_{h}_available'].sum()):,}/{len(frame):,}" for h in horizons))
    return "\n".join(lines)
