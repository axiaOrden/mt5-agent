"""Independent real-body engulfing events."""
from .models import EventType


def engulfing(previous_open: float, previous_close: float, current_open: float, current_close: float) -> EventType | None:
    if current_close > current_open and previous_close < previous_open and current_open <= previous_close and current_close >= previous_open:
        return EventType.BULLISH_ENGULFING
    if current_close < current_open and previous_close > previous_open and current_open >= previous_close and current_close <= previous_open:
        return EventType.BEARISH_ENGULFING
    return None
