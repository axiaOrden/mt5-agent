"""Stable flattened Parquet export for historical event research."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import ReplayResult


def replay_frame(result: ReplayResult) -> pd.DataFrame:
    rows = []
    for event in result.events:
        row = {
            "symbol": event.symbol, "event_timeframe": event.event_timeframe,
            "event_bar_open_time": event.event_bar_open_time,
            "event_knowledge_time": event.event_knowledge_time,
            "event_type": event.event_type.value,
            "event_direction": event.event_direction.value,
            "previous_state": event.previous_state.value, "new_state": event.new_state.value,
            "label": event.label,
            "event_open": event.event_candle.open, "event_high": event.event_candle.high,
            "event_low": event.event_candle.low, "event_close": event.event_candle.close,
            "event_tick_volume": event.event_candle.tick_volume,
            "event_real_volume": event.event_candle.real_volume,
        }
        pvsra = event.event_pvsra
        row.update({
            "pvsra_classification": pvsra.classification.value if pvsra else "UNAVAILABLE",
            "pvsra_direction": pvsra.candle_direction.value if pvsra else None,
            "pvsra_volume_source": pvsra.volume_source.value if pvsra else None,
            "pvsra_volume_ratio": pvsra.volume_ratio if pvsra else None,
            "pvsra_spread_ratio": pvsra.spread_ratio if pvsra else None,
            "pvsra_displacement_ratio": pvsra.vwap_displacement_ratio if pvsra else None,
        })
        for context in event.timeframe_contexts:
            prefix = context.timeframe.lower()
            row.update({
                f"{prefix}_role": context.role.value,
                f"{prefix}_direction": context.market_direction,
                f"{prefix}_condition": context.market_condition,
                f"{prefix}_market_state_candle_time": context.market_candle_time,
                f"{prefix}_cloudgazer_state": context.cloudgazer_state.value if context.cloudgazer_state else None,
                f"{prefix}_structural_alignment": context.structural_alignment.value,
                f"{prefix}_cloudgazer_alignment": context.cloudgazer_alignment.value,
                f"{prefix}_latest_state_event_time": context.latest_state_event_time,
                f"{prefix}_latest_state_event_age": context.state_event_age_bars,
                f"{prefix}_recent_state_changes": context.recent_state_changes,
                f"{prefix}_observed_bars": context.observed_bars,
            })
        for outcome in event.outcomes:
            prefix = f"forward_{outcome.horizon}"
            row.update({
                f"{prefix}_available": outcome.available,
                f"{prefix}_close": outcome.future_close,
                f"{prefix}_return": outcome.raw_return,
                f"{prefix}_directional_return": outcome.directional_return,
                f"{prefix}_mfe": outcome.mfe, f"{prefix}_mae": outcome.mae,
            })
        rows.append(row)
    frame = pd.DataFrame(rows)
    for column in ("event_bar_open_time", "event_knowledge_time"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def export_parquet(result: ReplayResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    replay_frame(result).to_parquet(path, index=False)
    return path
