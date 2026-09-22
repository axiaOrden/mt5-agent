"""Forward price measurements, isolated from event-time classification."""
from __future__ import annotations

import pandas as pd

from ..context.models import Direction
from .models import ForwardOutcome


def measure_forward_outcomes(
    bars: pd.DataFrame,
    event_index: int,
    reference_price: float,
    direction: Direction,
    horizons: tuple[int, ...],
) -> tuple[ForwardOutcome, ...]:
    """Measure the next N bars; the event candle at ``event_index`` is excluded.

    MFE and MAE are nonnegative magnitudes. A zero value means the future
    window never exceeded the event close in that favorable/adverse direction.
    """
    results = []
    for horizon in horizons:
        if horizon < 1:
            raise ValueError("forward horizons must be positive")
        end = event_index + horizon
        if end >= len(bars):
            results.append(ForwardOutcome(horizon, False, None, None, None, None, None))
            continue
        future = bars.iloc[event_index + 1:end + 1]
        future_close = float(future["close"].iloc[-1])
        raw_return = (future_close - reference_price) / reference_price
        if direction == Direction.BULLISH:
            directional_return = raw_return
            mfe = max(0.0, (float(future["high"].max()) - reference_price) / reference_price)
            mae = max(0.0, (reference_price - float(future["low"].min())) / reference_price)
        else:
            directional_return = -raw_return
            mfe = max(0.0, (reference_price - float(future["low"].min())) / reference_price)
            mae = max(0.0, (float(future["high"].max()) - reference_price) / reference_price)
        results.append(ForwardOutcome(
            horizon, True, future_close, raw_return, directional_return, mfe, mae
        ))
    return tuple(results)
