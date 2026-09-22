"""Market-state domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class TimeframeState:
    """Ichimoku interpretation for a single symbol/timeframe pair.

    ``candle_time`` is the opening timestamp of the latest COMPLETED candle
    that produced this state. Strategy analysis never uses a forming candle.

    ``direction`` describes the established trend; ``condition`` describes
    the regime. Contradictory components stay visible in the component
    fields and are never hidden behind a single arithmetic score.
    """

    symbol: str
    timeframe: str
    candle_time: Optional[datetime] = None
    candle_closed: bool = True
    price_vs_kumo: str = "N/A"  # ABOVE | INSIDE | BELOW (current Kumo at candle)
    tenkan_vs_kijun: str = "N/A"  # BULLISH | NEUTRAL | BEARISH
    projected_kumo: str = "N/A"  # BULLISH | NEUTRAL | BEARISH (unshifted cloud)
    chikou: str = "N/A"  # BULLISH | NEUTRAL | BEARISH (directional confirmation)
    chikou_obstructed: bool = False  # confirmation entangled with historical Kumo
    kijun_slope: str = "N/A"  # RISING | FLAT | FALLING
    kumo_thickness_atr: Optional[float] = None
    direction: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL
    condition: str = "TRANSITION"  # ESTABLISHED | TRANSITION | REVERSAL_ATTEMPT | MIXED
    score: int = 0  # diagnostic only; never the sole classification

    def __str__(self) -> str:
        return f"{self.direction}/{self.condition}"


@dataclass(frozen=True)
class MarketState:
    """Multi-timeframe market state for one symbol."""

    symbol: str
    timeframes: dict[str, TimeframeState] = field(default_factory=dict)

    def state_for(self, timeframe: str) -> Optional[TimeframeState]:
        return self.timeframes.get(timeframe)
