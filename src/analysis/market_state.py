"""Deterministic Ichimoku market-state interpretation.

``ichimoku.py`` computes raw values; this module interprets them. No LLM is
involved.

Closed-candle invariant
-----------------------
The analyzer only ever sees closed-candle history (enforced at the data
layer). When ``broker_now`` is supplied, the input is additionally filtered
to completed bars before analysis, and ``candle_time`` is the opening
timestamp of the latest completed candle.

Current Kumo vs Projected Kumo
------------------------------
* Price vs Kumo uses the PLOTTING-ALIGNED (shifted) spans: the cloud located
  at the current candle, computed from values 26 bars earlier.
* Projected Kumo uses the UNSHIFTED current calculations: the cloud that
  will be plotted 26 bars ahead.

Chikou
------
The current close is evaluated against the historical price structure at the
26-bars-back location (the candle the Chikou span is plotted against):
above the historical high AND above the historical Kumo -> BULLISH (clean);
below both -> BEARISH (clean); above one but entangled with the Kumo ->
directional but obstructed; inside the historical range -> NEUTRAL.

Direction / Condition
---------------------
``direction`` (established trend) requires price position to be confirmed by
structure. ``condition`` (regime) keeps contradictions visible:

    ESTABLISHED       direction confirmed, no opposing structural votes
    TRANSITION        direction present but weakly supported
    REVERSAL_ATTEMPT  price position opposes a strong structural majority
    MIXED             components contradict without a clear split

The numeric score is retained as a diagnostic summary only; it never
obscures the component state.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from ..indicators.ichimoku import atr, ichimoku
from ..models import MarketState, TimeframeState
from ..mt5.closure import filter_closed_bars

logger = logging.getLogger(__name__)

# Minimum bars so the current cloud (Senkou B over 52 bars displaced 26) is
# fully formed at the last row: 52 + 26.
MIN_BARS = 78

_SLOPE_LOOKBACK = 3
_SLOPE_TOLERANCE = 1e-4

_DISPLACEMENT = 26

# Component value -> score contribution (diagnostic only).
_SCORES = {
    "ABOVE": 1, "INSIDE": 0, "BELOW": -1,
    "BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1,
    "RISING": 1, "FLAT": 0, "FALLING": -1,
}


class MarketStateAnalyzer:
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        broker_now: Optional[datetime] = None,
    ) -> TimeframeState:
        """Interpret one symbol/timeframe history into a TimeframeState.

        ``broker_now`` (broker tick time) optionally enforces the
        closed-candle invariant: any forming bar is dropped before analysis.
        """
        if df is not None and broker_now is not None:
            df = filter_closed_bars(df, timeframe, broker_now)

        if df is None or len(df) < MIN_BARS:
            logger.warning(
                "insufficient bars for %s %s (%d < %d); state NEUTRAL/TRANSITION",
                symbol, timeframe, 0 if df is None else len(df), MIN_BARS,
            )
            return TimeframeState(symbol, timeframe, None, True)

        result = ichimoku(df)
        last = len(df) - 1
        candle_time = pd.Timestamp(df["time"].iloc[last]).to_pydatetime()

        close = float(df["close"].iloc[last])
        # Current-location cloud (plotting-aligned, shifted spans).
        span_a = float(result.senkou_span_a.iloc[last])
        span_b = float(result.senkou_span_b.iloc[last])
        # Projected cloud (unshifted current calculations).
        proj_a = float(result.senkou_span_a_projected.iloc[last])
        proj_b = float(result.senkou_span_b_projected.iloc[last])
        tenkan = float(result.tenkan_sen.iloc[last])
        kijun = float(result.kijun_sen.iloc[last])

        if any(pd.isna(v) for v in (span_a, span_b, proj_a, proj_b, tenkan, kijun)):
            logger.warning("NaN ichimoku values for %s %s; state NEUTRAL/TRANSITION", symbol, timeframe)
            return TimeframeState(symbol, timeframe, candle_time, True)

        price_vs_kumo = self._price_vs_kumo(close, span_a, span_b)
        tenkan_vs_kijun = self._compare(tenkan, kijun)
        projected_kumo = self._compare(proj_a, proj_b)
        chikou, chikou_obstructed = self._chikou(df, result, last)
        kijun_slope = self._slope(result.kijun_sen, last)
        thickness = self._kumo_thickness_atr(df, span_a, span_b, last)

        score = (
            _SCORES[price_vs_kumo]
            + _SCORES[tenkan_vs_kijun]
            + _SCORES[projected_kumo]
            + _SCORES[chikou]
            + _SCORES[kijun_slope]
        )
        direction, condition = self._classify(
            price_vs_kumo, tenkan_vs_kijun, projected_kumo, chikou, kijun_slope
        )

        return TimeframeState(
            symbol=symbol,
            timeframe=timeframe,
            candle_time=candle_time,
            candle_closed=True,
            price_vs_kumo=price_vs_kumo,
            tenkan_vs_kijun=tenkan_vs_kijun,
            projected_kumo=projected_kumo,
            chikou=chikou,
            chikou_obstructed=chikou_obstructed,
            kijun_slope=kijun_slope,
            kumo_thickness_atr=thickness,
            direction=direction,
            condition=condition,
            score=score,
        )

    def analyze_multi(
        self,
        histories: dict[str, pd.DataFrame],
        symbol: str,
        broker_now: Optional[datetime] = None,
    ) -> MarketState:
        """Analyze a symbol across multiple timeframes."""
        return MarketState(
            symbol=symbol,
            timeframes={
                tf: self.analyze(df, symbol, tf, broker_now=broker_now)
                for tf, df in histories.items()
                if df is not None
            },
        )

    # -- components --------------------------------------------------------

    @staticmethod
    def _price_vs_kumo(close: float, span_a: float, span_b: float) -> str:
        upper, lower = max(span_a, span_b), min(span_a, span_b)
        if close > upper:
            return "ABOVE"
        if close < lower:
            return "BELOW"
        return "INSIDE"

    @staticmethod
    def _compare(a: float, b: float) -> str:
        if a > b:
            return "BULLISH"
        if a < b:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _chikou(df: pd.DataFrame, result, last: int) -> tuple[str, bool]:
        """Chikou directional confirmation.

        The Chikou span plots the current close against the price structure
        26 bars back. Compare ``close[last]`` with the historical candle's
        high/low and the historical Kumo at ``ref = last - 26``:

            above high AND above Kumo   -> BULLISH, clean
            below low AND below Kumo    -> BEARISH, clean
            above one of them           -> BULLISH, obstructed
            below one of them           -> BEARISH, obstructed
            inside the historical range -> NEUTRAL, obstructed
        """
        ref = last - _DISPLACEMENT
        if ref < 0:
            return "NEUTRAL", True
        current_close = float(df["close"].iloc[last])
        ref_high = float(df["high"].iloc[ref])
        ref_low = float(df["low"].iloc[ref])
        ref_a = float(result.senkou_span_a.iloc[ref])
        ref_b = float(result.senkou_span_b.iloc[ref])
        if pd.isna(ref_a) or pd.isna(ref_b):
            return "NEUTRAL", True
        kumo_upper, kumo_lower = max(ref_a, ref_b), min(ref_a, ref_b)

        above_structure = current_close > ref_high
        below_structure = current_close < ref_low
        above_kumo = current_close > kumo_upper
        below_kumo = current_close < kumo_lower

        if above_structure and above_kumo:
            return "BULLISH", False
        if below_structure and below_kumo:
            return "BEARISH", False
        if above_structure or above_kumo:
            return "BULLISH", True
        if below_structure or below_kumo:
            return "BEARISH", True
        return "NEUTRAL", True

    @staticmethod
    def _slope(series: pd.Series, last: int) -> str:
        ref = last - _SLOPE_LOOKBACK
        if ref < 0:
            return "FLAT"
        current = float(series.iloc[last])
        previous = float(series.iloc[ref])
        if previous == 0:
            return "FLAT"
        change = (current - previous) / abs(previous)
        if change > _SLOPE_TOLERANCE:
            return "RISING"
        if change < -_SLOPE_TOLERANCE:
            return "FALLING"
        return "FLAT"

    @staticmethod
    def _kumo_thickness_atr(df: pd.DataFrame, span_a: float, span_b: float, last: int) -> float:
        a = atr(df, 14)
        value = float(a.iloc[last])
        if pd.isna(value) or value <= 0:
            return 0.0
        return abs(span_a - span_b) / value

    # -- classification ----------------------------------------------------

    @staticmethod
    def _classify(
        price_vs_kumo: str,
        tenkan_vs_kijun: str,
        projected_kumo: str,
        chikou: str,
        kijun_slope: str,
    ) -> tuple[str, str]:
        """Direction (established trend) and condition (regime).

        Direction requires price position confirmed by structure; a price
        position opposed by a strong structural majority is a REVERSAL_ATTEMPT,
        never an established trend.
        """
        structural = [tenkan_vs_kijun, projected_kumo, chikou, kijun_slope]
        bullish_votes = sum(1 for v in structural if v == "BULLISH")
        bearish_votes = sum(1 for v in structural if v == "BEARISH")

        if price_vs_kumo == "ABOVE" and (tenkan_vs_kijun == "BULLISH" or projected_kumo == "BULLISH"):
            direction = "BULLISH"
        elif price_vs_kumo == "BELOW" and (tenkan_vs_kijun == "BEARISH" or projected_kumo == "BEARISH"):
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        if direction == "BULLISH":
            if bearish_votes == 0 and bullish_votes >= 2:
                condition = "ESTABLISHED"
            elif bearish_votes >= 2:
                condition = "MIXED"
            else:
                condition = "TRANSITION"
        elif direction == "BEARISH":
            if bullish_votes == 0 and bearish_votes >= 2:
                condition = "ESTABLISHED"
            elif bullish_votes >= 2:
                condition = "MIXED"
            else:
                condition = "TRANSITION"
        else:
            if price_vs_kumo == "INSIDE":
                condition = "TRANSITION"
            elif price_vs_kumo == "ABOVE" and bearish_votes >= 3:
                condition = "REVERSAL_ATTEMPT"
            elif price_vs_kumo == "BELOW" and bullish_votes >= 3:
                condition = "REVERSAL_ATTEMPT"
            else:
                condition = "MIXED"

        return direction, condition
