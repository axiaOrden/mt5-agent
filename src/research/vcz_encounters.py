"""Causal, native-timeframe observations of encounters with surviving VCZs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Sequence

import math
import pandas as pd

from ..indicators.ichimoku import ichimoku
from ..mt5.closure import bar_duration
from ..pvsra.models import CandleDirection, PVSRAClassification, PVSRAResult
from .vcz import VCZSide, VCZStatus, VCZZone, _update, replay_vcz

DEFAULT_ENCOUNTER_HORIZONS = (1, 4, 8, 16, 32)


class RecoveryEffect(str, Enum):
    UNCHANGED = "UNCHANGED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    FULLY_RECOVERED = "FULLY_RECOVERED"


@dataclass(frozen=True)
class VCZEncounterOutcome:
    horizon: int
    available: bool
    future_close: float | None
    future_highest_high: float | None
    future_lowest_low: float | None
    close_return: float | None
    upward_excursion: float | None
    downward_excursion: float | None
    zone_fully_recovered: bool | None
    bars_until_full_recovery: int | None


@dataclass(frozen=True)
class VCZEncounter:
    encounter_id: str
    zone_id: str
    symbol: str
    timeframe: str
    side: VCZSide
    candle_open_time: datetime
    candle_close_time: datetime
    open: float
    high: float
    low: float
    close: float
    source_bar_open_time: datetime
    source_bar_close_time: datetime
    source_pvsra_classification: PVSRAClassification
    source_pvsra_direction: CandleDirection
    source_pvsra_flag: int
    source_volume: float | None
    source_volume_source: str
    original_bottom: float
    original_top: float
    pre_bottom: float
    pre_top: float
    post_bottom: float
    post_top: float
    post_status: VCZStatus
    overlap_bottom: float
    overlap_top: float
    overlap_height: float
    penetration_fraction: float | None
    zone_age_bars: int
    previous_close_position: str
    encounter_ordinal: int
    recovery_effect: RecoveryEffect
    candle_pvsra_classification: PVSRAClassification
    candle_pvsra_direction: CandleDirection
    price_vs_kumo: str
    price_vs_kijun: str
    kumo_orientation: str
    outcomes: tuple[VCZEncounterOutcome, ...]


@dataclass(frozen=True)
class VCZEncounterReplay:
    symbol: str
    timeframe: str
    candles_processed: int
    zones_created: int
    encounters: tuple[VCZEncounter, ...]


def _comparison(value: float, lower: float, upper: float, *, inside: str) -> str:
    if not all(math.isfinite(v) for v in (value, lower, upper)):
        return "UNAVAILABLE"
    if value > upper:
        return "ABOVE" if inside == "INSIDE" else "ABOVE_ZONE"
    if value < lower:
        return "BELOW" if inside == "INSIDE" else "BELOW_ZONE"
    return inside


def _context(indicator, close: float, i: int) -> tuple[str, str, str]:
    kijun = float(indicator.kijun_sen.iloc[i])
    a = float(indicator.senkou_span_a.iloc[i])
    b = float(indicator.senkou_span_b.iloc[i])
    cloud = _comparison(close, min(a, b), max(a, b), inside="INSIDE")
    kijun_relation = _comparison(close, kijun, kijun, inside="AT")
    orientation = ("UNAVAILABLE" if not math.isfinite(a) or not math.isfinite(b)
                   else "BULLISH" if a > b else "BEARISH" if a < b else "FLAT")
    return cloud, kijun_relation, orientation


def replay_vcz_encounters(bars: pd.DataFrame, pvsra_results: Sequence[PVSRAResult | None], *,
                          symbol: str, timeframe: str,
                          horizons: Sequence[int] = DEFAULT_ENCOUNTER_HORIZONS,
                          as_of: datetime | None = None) -> VCZEncounterReplay:
    """Observe each pre-bar surviving zone before V1 applies this bar's recovery.

    All input bars must be completed; `as_of` truncates by candle close. Outcomes
    use only the eligible suffix. VCZ V1 remains the lifecycle authority.
    """
    horizon_values = tuple(horizons)
    if not horizon_values or any(not isinstance(h, int) or h < 1 for h in horizon_values) or len(set(horizon_values)) != len(horizon_values):
        raise ValueError("horizons must be unique positive integers")
    lifecycle = replay_vcz(bars, pvsra_results, symbol=symbol, timeframe=timeframe, as_of=as_of)
    size = lifecycle.candles_processed
    if not size:
        return VCZEncounterReplay(symbol, timeframe, 0, 0, ())
    frame = bars.iloc[:size].reset_index(drop=True)
    values = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    times = pd.to_datetime(frame["time"], utc=True)
    duration = pd.Timedelta(bar_duration(timeframe))
    indicator = ichimoku(frame)
    created: dict[int, list[VCZZone]] = {}
    final = {z.zone_id: z for z in lifecycle.zones}
    for zone in lifecycle.zones:
        created.setdefault(zone.created_bar_index, []).append(zone)
    active: dict[str, VCZZone] = {}
    ordinals: dict[str, int] = {}
    observed: list[tuple[VCZEncounter, int]] = []
    for i in range(1, size):
        open_time = times.iloc[i].to_pydatetime()
        close_time = (times.iloc[i] + duration).to_pydatetime()
        o, high, low, close = map(float, values[i])
        # Capture the entire encounter set before any current-bar recovery or creation.
        overlaps = [z for z in active.values() if high >= z.current_bottom and low <= z.current_top]
        before = {z.zone_id: z for z in overlaps}
        for zone in created.get(i, ()):
            active[zone.zone_id] = replace(zone, current_bottom=zone.original_bottom,
                                           current_top=zone.original_top, last_updated_at=None,
                                           fully_recovered_at=None, fully_recovered_bar_index=None,
                                           partial_update_count=0)
        updated = {identity: _update(zone, zone.side, close, high, low, close_time, i)
                   for identity, zone in active.items()}
        cloud, kijun, orientation = _context(indicator, close, i)
        fact = pvsra_results[i]
        for identity, pre in before.items():
            post = updated[identity]
            overlap_bottom = max(low, pre.current_bottom)
            overlap_top = min(high, pre.current_top)
            overlap_height = max(0.0, overlap_top - overlap_bottom)
            height = pre.current_top - pre.current_bottom
            ordinals[identity] = ordinals.get(identity, 0) + 1
            effect = (RecoveryEffect.FULLY_RECOVERED if post.status == VCZStatus.FULLY_RECOVERED else
                      RecoveryEffect.PARTIALLY_RECOVERED if (post.current_bottom, post.current_top) !=
                      (pre.current_bottom, pre.current_top) else RecoveryEffect.UNCHANGED)
            encounter_id = sha256(f"{identity}|{open_time.isoformat()}".encode()).hexdigest()[:24]
            record = VCZEncounter(
                encounter_id, identity, symbol, timeframe, pre.side, open_time, close_time,
                o, high, low, close, pre.source_bar_open_time, pre.source_bar_close_time,
                pre.pvsra_classification, pre.pvsra_candle_direction, pre.pvsra_flag,
                pre.volume, pre.volume_source.value, pre.original_bottom, pre.original_top,
                pre.current_bottom, pre.current_top, post.current_bottom, post.current_top,
                post.status, overlap_bottom, overlap_top, overlap_height,
                overlap_height / height if height > 0 else None, i - pre.created_bar_index,
                _comparison(float(values[i - 1, 3]), pre.current_bottom, pre.current_top,
                            inside="INSIDE_ZONE"), ordinals[identity], effect,
                fact.classification if fact else PVSRAClassification.UNAVAILABLE,
                fact.candle_direction if fact else CandleDirection.NEUTRAL,
                cloud, kijun, orientation, ())
            observed.append((record, i))
        active = {identity: zone for identity, zone in updated.items()
                  if zone.status == VCZStatus.REMAINING}
    output = []
    for event, i in observed:
        recovered_at = final[event.zone_id].fully_recovered_bar_index
        outcomes = []
        for horizon in horizon_values:
            available = i + horizon < size
            future = values[i + 1:i + horizon + 1] if available else None
            recovery = None if not available else recovered_at is not None and recovered_at <= i + horizon
            outcomes.append(VCZEncounterOutcome(
                horizon, available, float(values[i + horizon, 3]) if available else None,
                float(future[:, 1].max()) if available else None,
                float(future[:, 2].min()) if available else None,
                (float(values[i + horizon, 3]) / event.close - 1) if available and event.close else None,
                float(future[:, 1].max() - event.close) if available else None,
                float(event.close - future[:, 2].min()) if available else None,
                recovery, recovered_at - i if recovery else None))
        output.append(replace(event, outcomes=tuple(outcomes)))
    return VCZEncounterReplay(symbol, timeframe, size, len(lifecycle.zones), tuple(output))


def encounters_frame(replay: VCZEncounterReplay) -> pd.DataFrame:
    """Stable flat primitive schema, one row per encounter."""
    rows = []
    for event in replay.encounters:
        data = asdict(event)
        data.pop("outcomes")
        for key, value in data.items():
            if isinstance(value, Enum):
                data[key] = value.value
        for outcome in event.outcomes:
            for key, value in asdict(outcome).items():
                if key != "horizon":
                    data[f"h{outcome.horizon}_{key}"] = value
        rows.append(data)
    return pd.DataFrame(rows)


def export_vcz_encounters(replay: VCZEncounterReplay, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encounters_frame(replay).to_parquet(path, index=False)
    return path
