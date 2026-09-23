"""Offline descriptive cohorts over persisted VCZ encounter observations."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .vcz_encounters import DEFAULT_ENCOUNTER_HORIZONS

AGE_LABELS = ("0-1", "2-4", "5-16", "17-64", "65-256", "257-1024", "1025+")
REMAINING_LABELS = (">0.75", "0.50-0.75", "0.25-0.50", "0.10-0.25", "<0.10")
DIMENSIONS = ("age", "remaining", "selector", "ordinal", "encounter-pvsra",
              "source-pvsra", "source-direction", "recovery", "kumo-position",
              "kijun-position", "kumo-orientation")
DIMENSION_COLUMNS = {
    "age": "age_bucket", "remaining": "remaining_bucket", "selector": "side",
    "ordinal": "ordinal_bucket", "encounter-pvsra": "candle_pvsra_classification",
    "source-pvsra": "source_pvsra_classification",
    "source-direction": "source_pvsra_direction", "recovery": "recovery_effect",
    "kumo-position": "kumo_position", "kijun-position": "kijun_position",
    "kumo-orientation": "kumo_orientation",
}
REQUIRED = ("encounter_id", "zone_id", "symbol", "timeframe", "candle_open_time",
            "source_bar_open_time", "encounter_ordinal", "zone_age_bars",
            "original_bottom", "original_top", "pre_bottom", "pre_top",
            "side", "candle_pvsra_classification", "source_pvsra_classification",
            "source_pvsra_direction", "recovery_effect", "price_vs_kumo",
            "price_vs_kijun", "kumo_orientation")
OUTCOME_FIELDS = ("available", "upward_excursion", "downward_excursion", "close_return")


def encounter_horizons(frame: pd.DataFrame) -> tuple[int, ...]:
    found = sorted(int(m.group(1)) for col in frame if (m := re.fullmatch(r"h(\d+)_available", col)))
    return tuple(h for h in found if all(f"h{h}_{field}" in frame for field in OUTCOME_FIELDS))


def validate_encounters(frame: pd.DataFrame, *, symbol: str | None = None,
                        timeframe: str | None = None) -> pd.DataFrame:
    """Reject incompatible or mixed native-timeframe artifacts before analysis."""
    missing = sorted(set(REQUIRED) - set(frame))
    if missing:
        raise ValueError(f"Encounter dataset missing fields: {', '.join(missing)}")
    advertised = {int(m.group(1)) for col in frame if (m := re.fullmatch(r"h(\d+)_available", col))}
    horizons = encounter_horizons(frame)
    if not horizons or advertised != set(horizons):
        raise ValueError("Encounter dataset has an incomplete outcome horizon schema")
    result = frame.copy()
    for column in ("candle_open_time", "source_bar_open_time"):
        result[column] = pd.to_datetime(result[column], utc=True, errors="raise")
        if result[column].isna().any():
            raise ValueError(f"Encounter dataset has null {column}")
    if result["encounter_id"].duplicated().any():
        raise ValueError("Encounter dataset has duplicate encounter IDs")
    if result["symbol"].nunique() != 1 or result["timeframe"].nunique() != 1:
        raise ValueError("Encounter dataset must contain one symbol and native timeframe")
    if symbol is not None and not result["symbol"].eq(symbol).all():
        raise ValueError("Encounter dataset symbol differs from requested symbol")
    if timeframe is not None and not result["timeframe"].eq(timeframe).all():
        raise ValueError("Encounter dataset timeframe differs from requested timeframe")
    if (result["encounter_ordinal"] < 1).any() or (result["zone_age_bars"] < 0).any():
        raise ValueError("Invalid encounter ordinal or zone age")
    categories = {
        "price_vs_kumo": {"ABOVE", "INSIDE", "BELOW", "UNAVAILABLE"},
        "price_vs_kijun": {"ABOVE", "ABOVE_ZONE", "AT", "BELOW", "BELOW_ZONE", "UNAVAILABLE"},
    }
    for column, allowed in categories.items():
        if not result[column].isin(allowed).all():
            raise ValueError(f"Encounter dataset has unknown {column} category")
    for h in horizons:
        available = f"h{h}_available"
        if not pd.api.types.is_bool_dtype(result[available]):
            raise ValueError(f"{available} must be boolean")
        columns = [f"h{h}_{field}" for field in OUTCOME_FIELDS[1:]]
        if any(not pd.api.types.is_numeric_dtype(result[c]) for c in columns):
            raise ValueError(f"Horizon {h} outcomes must be numeric")
        if result.loc[result[available], columns].isna().any().any():
            raise ValueError(f"Horizon {h} available outcomes cannot be missing")
    return result


def load_encounters(path: str | Path, *, symbol: str | None = None,
                    timeframe: str | None = None) -> pd.DataFrame:
    return validate_encounters(pd.read_parquet(path), symbol=symbol, timeframe=timeframe)


def age_bucket(age: int) -> str:
    if age < 0:
        raise ValueError("zone age cannot be negative")
    for upper, label in zip((1, 4, 16, 64, 256, 1024), AGE_LABELS):
        if age <= upper:
            return label
    return AGE_LABELS[-1]


def remaining_bucket(fraction: float) -> str:
    if not np.isfinite(fraction) or fraction < 0 or fraction > 1:
        return "UNAVAILABLE"
    if fraction > .75:
        return REMAINING_LABELS[0]
    if fraction > .5:
        return REMAINING_LABELS[1]
    if fraction > .25:
        return REMAINING_LABELS[2]
    if fraction >= .1:
        return REMAINING_LABELS[3]
    return REMAINING_LABELS[4]


def prepare_encounters(frame: pd.DataFrame) -> pd.DataFrame:
    """Add only analysis labels; preserve every persisted observation value."""
    result = validate_encounters(frame)
    result["age_bucket"] = pd.cut(result["zone_age_bars"],
                                   bins=[-1, 1, 4, 16, 64, 256, 1024, np.inf],
                                   labels=AGE_LABELS).astype(str)
    height = result["original_top"] - result["original_bottom"]
    fraction = (result["pre_top"] - result["pre_bottom"]) / height.where(height > 0)
    result["pre_remaining_fraction"] = fraction
    result["remaining_bucket"] = fraction.map(remaining_bucket)
    result["ordinal_bucket"] = np.where(result["encounter_ordinal"].eq(1), "1",
                                         np.where(result["encounter_ordinal"].eq(2), "2", "3+"))
    result["kumo_position"] = result["price_vs_kumo"].map({
        "ABOVE": "ABOVE_KUMO", "INSIDE": "INSIDE_KUMO", "BELOW": "BELOW_KUMO",
        "UNAVAILABLE": "UNAVAILABLE"}).fillna("UNAVAILABLE")
    result["kijun_position"] = result["price_vs_kijun"].map({
        "ABOVE": "ABOVE_KIJUN", "ABOVE_ZONE": "ABOVE_KIJUN",
        "AT": "AT_KIJUN", "BELOW": "BELOW_KIJUN", "BELOW_ZONE": "BELOW_KIJUN",
        "UNAVAILABLE": "UNAVAILABLE"}).fillna("UNAVAILABLE")
    return result


def population_frame(frame: pd.DataFrame, population: str) -> pd.DataFrame:
    if population == "ALL":
        return frame
    if population == "FIRST":
        result = frame.loc[frame["encounter_ordinal"].eq(1)]
        if result["zone_id"].duplicated().any():
            raise ValueError("FIRST population contains multiple first encounters for one zone")
        return result
    raise ValueError("population must be ALL or FIRST")


def inventory(frame: pd.DataFrame) -> dict:
    counts = frame.groupby("candle_open_time", sort=False).size()
    return {
        "encounters": len(frame), "unique_zones": frame["zone_id"].nunique(),
        "unique_source_candles": frame["source_bar_open_time"].nunique(),
        "first_encounters": int(frame["encounter_ordinal"].eq(1).sum()),
        "later_encounters": int(frame["encounter_ordinal"].gt(1).sum()),
        "encounter_candles_1_zone": int(counts.eq(1).sum()),
        "encounter_candles_2_zones": int(counts.eq(2).sum()),
        "encounter_candles_3plus_zones": int(counts.ge(3).sum()),
    }


def _periods(frame: pd.DataFrame, segment: str):
    yield "full", "FULL", frame
    dates = frame["candle_open_time"].dt
    period = dates.strftime("%Y") if segment == "year" else dates.year.astype(str) + "-Q" + dates.quarter.astype(str)
    for key, group in frame.groupby(period, sort=True):
        yield segment, str(key), group


def _cohort_groups(frame: pd.DataFrame, dimension: str):
    if dimension == "overall":
        yield "ALL", frame
    else:
        for key, group in frame.groupby(DIMENSION_COLUMNS[dimension], sort=True, observed=True, dropna=False):
            yield str(key), group


def cohort_study(frame: pd.DataFrame, *, populations=("ALL", "FIRST"),
                 segment: str = "year", dimensions=DIMENSIONS,
                 horizons=DEFAULT_ENCOUNTER_HORIZONS,
                 min_sample: int = 30) -> pd.DataFrame:
    """One dimension at a time, for full period and each calendar segment."""
    if segment not in ("year", "quarter"):
        raise ValueError("segment must be year or quarter")
    if min_sample < 1:
        raise ValueError("min_sample must be positive")
    if any(d not in DIMENSIONS for d in dimensions):
        raise ValueError("unknown encounter study dimension")
    horizons = tuple(horizons)
    if not horizons or len(set(horizons)) != len(horizons) or any(h not in encounter_horizons(frame) for h in horizons):
        raise ValueError("requested outcome horizon is unavailable")
    prepared = prepare_encounters(frame)
    rows = []
    for population in populations:
        source = population_frame(prepared, population)
        for period_type, period, subset in _periods(source, segment):
            for dimension in ("overall", *dimensions):
                if population == "FIRST" and dimension == "ordinal":
                    continue
                for cohort, group in _cohort_groups(subset, dimension):
                    n = len(group)
                    common = {
                        "population": population, "symbol": str(group["symbol"].iloc[0]),
                        "timeframe": str(group["timeframe"].iloc[0]),
                        "period_type": period_type, "period": period,
                        "dimension": dimension, "cohort": cohort, "n": n,
                        "unique_zones": group["zone_id"].nunique(),
                        "unique_source_candles": group["source_bar_open_time"].nunique(),
                        "median_zone_age_bars": group["zone_age_bars"].median(),
                        "q25_zone_age_bars": group["zone_age_bars"].quantile(.25),
                        "q75_zone_age_bars": group["zone_age_bars"].quantile(.75),
                        "max_zone_age_bars": group["zone_age_bars"].max(),
                        "median_pre_remaining_fraction": group["pre_remaining_fraction"].median(),
                        "same_candle_full_count": int(group["recovery_effect"].eq("FULLY_RECOVERED").sum()),
                        "same_candle_partial_count": int(group["recovery_effect"].eq("PARTIALLY_RECOVERED").sum()),
                        "same_candle_unchanged_count": int(group["recovery_effect"].eq("UNCHANGED").sum()),
                        "small_sample": n < min_sample,
                    }
                    common["same_candle_full_rate"] = common["same_candle_full_count"] / n
                    common["same_candle_partial_rate"] = common["same_candle_partial_count"] / n
                    common["same_candle_unchanged_rate"] = common["same_candle_unchanged_count"] / n
                    for h in horizons:
                        available = group.loc[group[f"h{h}_available"]]
                        up = available[f"h{h}_upward_excursion"]
                        down = available[f"h{h}_downward_excursion"]
                        close = available[f"h{h}_close_return"]
                        recovered = available[f"h{h}_zone_fully_recovered"] if f"h{h}_zone_fully_recovered" in available else pd.Series(dtype=bool)
                        recovery_bars = available[f"h{h}_bars_until_full_recovery"] if f"h{h}_bars_until_full_recovery" in available else pd.Series(dtype=float)
                        rows.append(common | {
                            "horizon": h, "n_available": len(available),
                            "median_upward_excursion": up.median(),
                            "q25_upward_excursion": up.quantile(.25), "q75_upward_excursion": up.quantile(.75),
                            "median_downward_excursion": down.median(),
                            "q25_downward_excursion": down.quantile(.25), "q75_downward_excursion": down.quantile(.75),
                            "median_close_return": close.median(),
                            "median_absolute_close_return": close.abs().median(),
                            "full_recovery_by_horizon_count": int(recovered.fillna(False).sum()),
                            "median_bars_until_full_recovery": recovery_bars.dropna().median(),
                        })
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["dimension", "cohort", "timeframe", "population",
                                     "period_type", "period", "horizon"], kind="stable").reset_index(drop=True)
    return result


def export_study(result: pd.DataFrame, path: str | Path, *, input_path: str | Path,
                 symbol: str, timeframe: str, populations, segment: str,
                 dimensions, horizons, min_sample: int) -> Path:
    destination = Path(path)
    if destination.suffix.lower() not in (".csv", ".parquet"):
        raise ValueError("output must be CSV or Parquet")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".csv":
        result.to_csv(destination, index=False, float_format="%.12g")
    else:
        result.to_parquet(destination, index=False)
    digest = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
    metadata = {
        "schema": "vcz-encounter-cohort-study-v1", "input_path": str(input_path),
        "input_sha256": digest, "symbol": symbol, "timeframe": timeframe,
        "populations": list(populations), "segment": segment,
        "dimensions": list(dimensions), "horizons": list(horizons),
        "min_sample": min_sample,
        "semantics": "one dimension at a time; raw native-timeframe encounter outcomes",
    }
    destination.with_name(destination.name + ".meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
