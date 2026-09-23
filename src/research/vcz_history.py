"""Offline adapter from saved native research candles to pure VCZ replay."""
from __future__ import annotations

from statistics import median

import pandas as pd

from ..signals.vwap_events import broker_session_anchors
from .pvsra_index import PVSRAIndex
from .vcz import VCZReplay, VCZStatus, replay_vcz


def replay_native_vcz(bars: pd.DataFrame, daily_bars: pd.DataFrame, *,
                      symbol: str, timeframe: str,
                      max_zones: int | None = None) -> VCZReplay:
    """Reuse existing PVSRA measurements on this timeframe's own bars."""
    if bars.empty:
        return VCZReplay(symbol, timeframe, 0, 0, (), None)
    anchors = broker_session_anchors(daily_bars, pd.Timestamp(bars["time"].iloc[-1]))
    index = PVSRAIndex(bars, anchors)
    results = [index.at(i) for i in range(len(bars))]
    return replay_vcz(bars, results, symbol=symbol, timeframe=timeframe,
                      max_zones=max_zones)


def vcz_summary(replay: VCZReplay) -> dict:
    surviving = replay.surviving_zones
    recovered = replay.fully_recovered_zones
    fractions = [zone.remaining_fraction for zone in surviving
                 if zone.remaining_fraction is not None]
    return {
        "symbol": replay.symbol,
        "timeframe": replay.timeframe,
        "candles_processed": replay.candles_processed,
        "qualifying_pvsra_source_candles": replay.qualifying_pvsra_source_candles,
        "zones_created": len(replay.zones),
        "zones_fully_recovered": len(recovered),
        "zones_remaining": len(surviving),
        "zones_partially_recovered_remaining": sum(zone.partially_recovered for zone in surviving),
        "zones_display_evicted": sum(zone.status == VCZStatus.DISPLAY_EVICTED for zone in replay.zones),
        "median_remaining_fraction": median(fractions) if fractions else None,
        "median_recovered_lifetime_bars": median(zone.bars_until_recovery for zone in recovered)
        if recovered else None,
    }
