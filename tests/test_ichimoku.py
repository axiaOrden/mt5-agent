"""Unit tests for the Ichimoku implementation (hand-computed values)."""

import numpy as np
import pandas as pd
import pytest

from src.indicators.ichimoku import atr, ichimoku


def _frame(n: int) -> pd.DataFrame:
    """high[i]=i+1, low[i]=i, close[i]=i+1 — strictly rising series."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "time": idx,
            "open": np.arange(1, n + 1, dtype=float),
            "high": np.arange(1, n + 1, dtype=float),
            "low": np.arange(0, n, dtype=float),
            "close": np.arange(1, n + 1, dtype=float),
        }
    )


def test_tenkan_sen_hand_computed():
    df = _frame(60)
    result = ichimoku(df)
    # tenkan at index 8: (highest high 9 + lowest low 9) / 2 = (9 + 0) / 2
    assert result.tenkan_sen.iloc[8] == pytest.approx(4.5)
    # tenkan at index 9: (10 + 1) / 2
    assert result.tenkan_sen.iloc[9] == pytest.approx(5.5)
    # first 8 values are NaN (not enough bars)
    assert result.tenkan_sen.iloc[:8].isna().all()


def test_kijun_sen_hand_computed():
    df = _frame(100)
    result = ichimoku(df)
    # kijun at index 25: (highest high 26 + lowest low 26) / 2 = (26 + 0) / 2
    assert result.kijun_sen.iloc[25] == pytest.approx(13.0)
    assert result.kijun_sen.iloc[:25].isna().all()


def test_senkou_span_a_displaced():
    df = _frame(100)
    result = ichimoku(df)
    # span A at index 26+25: (tenkan[25] + kijun[25]) / 2 = (21.5 + 13) / 2
    assert result.senkou_span_a.iloc[51] == pytest.approx(17.25)
    # span A is tenkan/kijun midpoint shifted forward by 26
    expected = ((result.tenkan_sen + result.kijun_sen) / 2.0).shift(26)
    pd.testing.assert_series_equal(
        result.senkou_span_a, expected, check_names=False
    )


def test_senkou_span_a_projected_is_unshifted():
    df = _frame(100)
    result = ichimoku(df)
    # Projected span A at index 51 uses the CURRENT tenkan/kijun (unshifted):
    # tenkan[51] = (52 + 43) / 2 = 47.5, kijun[51] = (52 + 26) / 2 = 39
    # -> (47.5 + 39) / 2 = 43.25.
    assert result.senkou_span_a_projected.iloc[51] == pytest.approx(43.25)
    # It differs from the plotting-aligned span at the same index (17.25).
    assert result.senkou_span_a_projected.iloc[51] != result.senkou_span_a.iloc[51]
    expected = (result.tenkan_sen + result.kijun_sen) / 2.0
    pd.testing.assert_series_equal(
        result.senkou_span_a_projected, expected, check_names=False
    )


def test_senkou_span_b_projected_is_unshifted():
    df = _frame(100)
    result = ichimoku(df)
    # Projected span B at index 51: 52-bar midpoint ending at 51 = (52 + 0) / 2.
    assert result.senkou_span_b_projected.iloc[51] == pytest.approx(26.0)
    expected = (df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2.0
    pd.testing.assert_series_equal(
        result.senkou_span_b_projected, expected, check_names=False
    )


def test_senkou_span_b_displaced():
    df = _frame(100)
    result = ichimoku(df)
    # span B at index 26+51: (highest high 52 + lowest low 52) / 2 = (52 + 0) / 2
    assert result.senkou_span_b.iloc[77] == pytest.approx(26.0)
    expected = ((df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2.0).shift(26)
    pd.testing.assert_series_equal(
        result.senkou_span_b, expected, check_names=False
    )


def test_chikou_span_displaced_backward():
    df = _frame(100)
    result = ichimoku(df)
    # chikou at index 0 = close at index 26
    assert result.chikou_span.iloc[0] == pytest.approx(27.0)
    # last 26 rows are NaN (close shifted back 26)
    assert result.chikou_span.iloc[-26:].isna().all()


def test_custom_parameters():
    df = _frame(100)
    result = ichimoku(df, tenkan=5, kijun=13, senkou_b=26, displacement=13)
    assert result.tenkan_sen.iloc[4] == pytest.approx(2.5)
    assert result.kijun_sen.iloc[12] == pytest.approx(6.5)
    assert result.senkou_span_b.iloc[13 + 25] == pytest.approx(13.0)


def test_empty_frame_raises():
    with pytest.raises(ValueError):
        ichimoku(pd.DataFrame())


def test_missing_column_raises():
    with pytest.raises(ValueError):
        ichimoku(pd.DataFrame({"high": [1.0], "low": [0.0]}))


def test_atr_positive_and_finite():
    df = _frame(100)
    values = atr(df, 14)
    assert values.iloc[13:].notna().all()
    assert (values.iloc[13:] > 0).all()
