import numpy as np
import pandas as pd
import pytest

from src.indicators import gap_pct, sma, trend_aligned


def test_sma_matches_manual_average():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = sma(s, 3)
    assert np.isnan(result.iloc[0]) and np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_sma_rejects_bad_window():
    with pytest.raises(ValueError):
        sma(pd.Series([1.0]), 0)


def test_trend_aligned_true_in_steady_uptrend():
    close = pd.Series(np.arange(100, 200, dtype=float))
    aligned = trend_aligned(close, fast=5, mid=10, slow=20)
    assert aligned.iloc[-1] is np.True_ or bool(aligned.iloc[-1]) is True


def test_trend_aligned_false_in_downtrend():
    close = pd.Series(np.arange(200, 100, -1, dtype=float))
    aligned = trend_aligned(close, fast=5, mid=10, slow=20)
    assert not bool(aligned.iloc[-1])


def test_trend_aligned_false_when_not_enough_history():
    close = pd.Series(np.arange(100, 110, dtype=float))
    aligned = trend_aligned(close, fast=5, mid=10, slow=20)
    assert not aligned.any()


def test_gap_pct():
    assert gap_pct(10.75, 10.00) == pytest.approx(7.5)
    with pytest.raises(ValueError):
        gap_pct(10.0, 0.0)
