import numpy as np
import pandas as pd
import pytest

from boursy.indicators.core import adjusted, atr, bollinger, compute_all, ema, macd, rsi, sma, snapshot

# Classic Wilder RSI example (StockCharts "RSI" article), 14 periods.
RSI_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
    46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18,
    44.22, 44.57, 43.42, 42.66, 43.13,
]  # fmt: skip
RSI_EXPECTED = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99]


def test_sma():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = sma(s, 3)
    assert out.isna().tolist() == [True, True, False, False, False]
    assert out.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_ema_seeded_with_sma():
    s = pd.Series([1.0, 2, 3, 4, 5, 6])
    out = ema(s, 3)
    alpha = 0.5
    expected3 = 2.0 + alpha * (4 - 2.0)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(expected3)
    assert out.iloc[4] == pytest.approx(expected3 + alpha * (5 - expected3))


def test_ema_handles_leading_nans():
    s = pd.Series([np.nan, np.nan, 1.0, 2.0, 3.0])
    out = ema(s, 2)
    assert np.isnan(out.iloc[2])
    assert out.iloc[3] == pytest.approx(1.5)


def test_rsi_matches_wilder_reference():
    out = rsi(pd.Series(RSI_CLOSES), 14)
    assert out.iloc[:14].isna().all()
    # Hand calculation on these 2-decimal closes: gains sum 3.34, losses sum 1.40 over 14 periods.
    assert out.iloc[14] == pytest.approx(100 - 100 / (1 + 3.34 / 1.40))
    # StockCharts computed its published values from unrounded prices, hence a small constant gap.
    got = out.iloc[14 : 14 + len(RSI_EXPECTED)].tolist()
    assert got == pytest.approx(RSI_EXPECTED, abs=0.1)


def test_rsi_extremes():
    assert rsi(pd.Series(np.arange(1.0, 40.0)), 14).iloc[-1] == 100.0
    assert rsi(pd.Series(np.arange(40.0, 1.0, -1)), 14).iloc[-1] == pytest.approx(0.0)
    assert rsi(pd.Series([10.0] * 30), 14).iloc[-1] == 50.0


def test_macd_is_difference_of_emas():
    s = pd.Series(np.linspace(10, 50, 80) + np.sin(np.arange(80)))
    m = macd(s)
    line = ema(s, 12) - ema(s, 26)
    pd.testing.assert_series_equal(m["macd"], line, check_names=False)
    assert m["macd_signal"].first_valid_index() == 25 + 8
    assert (m["macd_hist"] - (m["macd"] - m["macd_signal"])).abs().max() < 1e-12


def test_atr_constant_range():
    n = 30
    close = pd.Series([100.0] * n)
    out = atr(close + 2, close - 2, close, 14)
    assert out.iloc[13] == pytest.approx(4.0)
    assert out.iloc[-1] == pytest.approx(4.0)


def test_atr_uses_gaps():
    high = pd.Series([11.0, 21.0])
    low = pd.Series([9.0, 19.0])
    close = pd.Series([10.0, 20.0])
    out = atr(high, low, close, 2)
    # TR = [2, max(2, 11, 9)] = [2, 11] -> ATR seed = 6.5
    assert out.iloc[1] == pytest.approx(6.5)


def test_bollinger_flat_series():
    bb = bollinger(pd.Series([5.0] * 25))
    assert bb["bb_upper"].iloc[-1] == bb["bb_lower"].iloc[-1] == 5.0


def test_adjusted_scales_ohlc():
    bars = pd.DataFrame(
        {"open": [10.0], "high": [12.0], "low": [9.0], "close": [10.0], "adj_close": [9.0], "volume": [1]}
    )
    adj = adjusted(bars)
    assert adj.loc[0, ["open", "high", "low", "close"]].tolist() == pytest.approx([9.0, 10.8, 8.1, 9.0])


def test_snapshot_trend_flags():
    n = 260
    idx = pd.Index(pd.date_range("2024-01-01", periods=n, freq="B").date, name="date")
    close = pd.Series(np.linspace(50, 100, n), index=idx)
    raw = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adj_close": close,
            "volume": 1000,
        },
        index=idx,
    )
    snap = snapshot(compute_all(raw), raw)
    assert snap["above_sma200"] is True
    assert snap["sma50_above_sma200"] is True
    assert snap["close"] == pytest.approx(100.0)
    assert snap["change_1d_pct"] > 0
