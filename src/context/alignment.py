"""Explicit, score-free direction and alignment rules."""
from __future__ import annotations

from ..signals.models import CloudgazerState, EventType
from .models import Alignment, Direction


_BULLISH_EVENTS = {EventType.VWAP_CROSS_BULLISH, EventType.TK_CROSS_BULLISH}
_BEARISH_EVENTS = {EventType.VWAP_CROSS_BEARISH, EventType.TK_CROSS_BEARISH}


def direction_for_event(event_type: EventType | None) -> Direction | None:
    """Directional intent for state-machine events; engulfing is contextual."""
    if event_type in _BULLISH_EVENTS:
        return Direction.BULLISH
    if event_type in _BEARISH_EVENTS:
        return Direction.BEARISH
    return None


def structural_alignment(direction: Direction | None, market_direction: str | None) -> Alignment:
    if direction is None or market_direction is None:
        return Alignment.UNAVAILABLE
    if market_direction == "NEUTRAL":
        return Alignment.NEUTRAL
    if market_direction == direction.value:
        return Alignment.ALIGNED
    if market_direction in (Direction.BULLISH.value, Direction.BEARISH.value):
        return Alignment.OPPOSED
    return Alignment.UNAVAILABLE


def cloudgazer_alignment(direction: Direction | None, state: CloudgazerState | None) -> Alignment:
    if direction is None or state is None:
        return Alignment.UNAVAILABLE
    if state == CloudgazerState.FLAT:
        return Alignment.NEUTRAL
    expected = CloudgazerState.LONG if direction == Direction.BULLISH else CloudgazerState.SHORT
    return Alignment.ALIGNED if state == expected else Alignment.OPPOSED
