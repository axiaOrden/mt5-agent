"""Chart-timeframe VWAP compatible with Cloudgazer's ``ta.vwap(hlc3)``.

Pine's implicit VWAP is a daily VWAP: it accumulates the active chart's
``hlc3 * volume`` values and resets when ``timeframe.change("1D")`` is true.
It does not secretly request lower-timeframe bars. Consequently, a D1 chart
has one observation per reset and its VWAP equals that D1 bar's HLC3. This is
odd as an analytical daily VWAP, but it is the behavior of Cloudgazer's Pine
expression and is intentionally preserved here.

``daily_opens`` should contain broker D1 opening timestamps. They identify
the broker trading day without consulting machine time. UTC dates are only a
documented fallback for callers that cannot supply broker D1 history.

MT5 ``tick_volume`` counts broker ticks, whereas TradingView's volume units
depend on its data feed. It is used because spot XAUUSD ``real_volume`` is
commonly zero. A session with no positive usable volume has undefined VWAP.
"""
from __future__ import annotations

import pandas as pd
from .models import EventType


def broker_session_anchors(daily_bars: pd.DataFrame, through: pd.Timestamp) -> pd.Series:
    """Return D1 opens, extending the latest known cadence through ``through``.

    The history store intentionally excludes the forming D1 candle. For live
    intraday analysis we therefore extend the last observed D1-open cadence
    in 24-hour steps. Empty weekend/holiday anchors do not affect results;
    they merely ensure the first available bar of the next broker day resets.
    Actual historical D1 timestamps always take precedence. A broker DST
    shift in the still-forming day cannot be known from closed bars alone.
    """
    if daily_bars is None or daily_bars.empty or "time" not in daily_bars:
        return pd.Series(dtype="datetime64[ns, UTC]")
    opens = pd.Series(pd.to_datetime(daily_bars["time"], utc=True).dropna().unique()).sort_values()
    if opens.empty:
        return pd.Series(dtype="datetime64[ns, UTC]")
    end = pd.Timestamp(through)
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    extended = list(opens)
    next_open = pd.Timestamp(extended[-1]) + pd.Timedelta(days=1)
    while next_open <= end:
        extended.append(next_open)
        next_open += pd.Timedelta(days=1)
    return pd.Series(pd.to_datetime(extended, utc=True))


def session_vwap(df: pd.DataFrame, daily_opens: pd.Series | None = None) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    times = pd.to_datetime(df["time"], utc=True)
    if daily_opens is None:
        anchor = times.dt.floor("D")
    else:
        opens = pd.to_datetime(daily_opens, utc=True).sort_values().reset_index(drop=True)
        if opens.empty:
            return pd.Series(float("nan"), index=df.index)
        # Map every intraday bar to the most recent actual broker D1 open.
        import numpy as np
        positions = np.searchsorted(opens.to_numpy(), times.to_numpy(), side="right") - 1
        anchor = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
        valid = positions >= 0
        anchor.loc[valid] = opens.iloc[positions[valid]].to_numpy()
    if "tick_volume" not in df:
        return pd.Series(float("nan"), index=df.index)
    volume = pd.to_numeric(df["tick_volume"], errors="coerce")
    if (volume < 0).any():
        raise ValueError("negative tick volume")
    source = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3
    # Missing volume makes that value and the remainder of its session
    # unknowable; do not silently reinterpret it as zero.
    missing_seen = volume.isna().groupby(anchor).cummax()
    weighted = (source * volume).groupby(anchor).cumsum()
    total = volume.groupby(anchor).cumsum()
    weighted = weighted.mask(missing_seen)
    total = total.mask(missing_seen)
    return weighted.div(total.where(total > 0))


def vwap_cross(previous_close: float, previous_vwap: float, current_close: float, current_vwap: float) -> EventType | None:
    if any(pd.isna(v) for v in (previous_close, previous_vwap, current_close, current_vwap)):
        return None
    if previous_close <= previous_vwap and current_close > current_vwap:
        return EventType.VWAP_CROSS_BULLISH
    if previous_close >= previous_vwap and current_close < current_vwap:
        return EventType.VWAP_CROSS_BEARISH
    return None
