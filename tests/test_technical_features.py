"""
Look-ahead bias and date-integrity tests for compute_technical_features().

Why these tests matter:
  The framework's Phase 0 gate requires zero look-ahead violations.  A
  rolling feature that accidentally uses future data produces inflated
  backtest returns that disappear in live trading.  These tests are the
  programmatic check for that gate requirement.

How pytest works (quick primer):
  - Any function starting with `test_` is auto-discovered and run.
  - `assert` statements are how you check correctness — if one fails,
    pytest shows you the exact values so you can diagnose the bug.
  - Run all tests with:  python -m pytest tests/ -v
"""

import numpy as np
import pandas as pd
import pytest

from data.technical_features import (
    _atr,
    _ema,
    _macd,
    _obv,
    _rsi,
    _sma,
    compute_technical_features,
)


def test_sma_basic():
    """SMA with constant values should return that constant."""
    series = pd.Series([100.0] * 10)
    result = _sma(series, 5)
    assert result.iloc[-1] == 100.0


def test_sma_length():
    """SMA produces first valid value at position length-1."""
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = _sma(series, 3)
    assert result.iloc[0] != result.iloc[0]
    assert np.isclose(result.iloc[2], 2.0)


def test_ema_basic():
    """EMA with constant values should return that constant."""
    series = pd.Series([50.0] * 20)
    result = _ema(series, 10)
    assert np.isclose(result.iloc[-1], 50.0, rtol=1e-6)


def test_rsi_range():
    """RSI must always be between 0 and 100."""
    rng = np.random.default_rng(42)
    series = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 100))))
    result = _rsi(series, 14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_constant():
    """RSI of constant prices should be undefined (NaN) or stabilize at 50."""
    series = pd.Series([100.0] * 50)
    result = _rsi(series, 14)
    valid = result.dropna()
    assert valid.empty or np.isclose(valid.iloc[-1], 50, atol=1)


def test_macd_structure():
    """MACD must return DataFrame with 3 columns."""
    series = pd.Series([100, 101, 102, 103, 104, 105] * 10)
    result = _macd(series, fast=12, slow=26, signal=9)
    assert len(result.columns) == 3
    assert "MACD_12_26_9" in result.columns
    assert "MACDs_12_26_9" in result.columns
    assert "MACDh_12_26_9" in result.columns
    assert len(result) == len(series)


def test_macd_histogram():
    """MACD histogram = MACD line - signal line."""
    series = pd.Series(
        100 * np.exp(np.cumsum(np.random.default_rng(42).normal(0, 0.01, 80)))
    )
    result = _macd(series, fast=12, slow=26, signal=9)
    macd = result["MACD_12_26_9"]
    signal = result["MACDs_12_26_9"]
    hist = result["MACDh_12_26_9"]
    diff = (macd - signal - hist).dropna()
    assert np.isclose(diff, 0, atol=1e-10).all()


def test_atr_basic():
    """ATR with no volatility (high=close=low) should be ~0."""
    close = pd.Series([100.0] * 20)
    high = close.copy()
    low = close.copy()
    result = _atr(high, low, close, 14)
    valid = result.dropna()
    assert (valid < 1.0).all()


def test_atr_increases_with_volatility():
    """ATR with high volatility should be larger than with low volatility."""
    close_stable = pd.Series([100.0] * 30)
    high_stable = close_stable + 0.5
    low_stable = close_stable - 0.5
    atr_stable = _atr(high_stable, low_stable, close_stable, 14).dropna()

    close_volatile = pd.Series([100.0, 105.0, 95.0, 110.0, 90.0] * 6)
    high_volatile = close_volatile + 5
    low_volatile = close_volatile - 5
    atr_volatile = _atr(high_volatile, low_volatile, close_volatile, 14).dropna()

    assert atr_volatile.mean() > atr_stable.mean()


def test_obv_basic():
    """OBV increases with volume on up days, decreases on down days."""
    close = pd.Series([100.0, 101.0, 99.0, 102.0])
    volume = pd.Series([1000, 2000, 1500, 3000])
    result = _obv(close, volume)
    assert result.iloc[0] == 0
    assert result.iloc[1] > result.iloc[0]
    assert result.iloc[2] < result.iloc[1]


def test_obv_flat():
    """OBV of flat prices returns 0 (no direction, no volume applied)."""
    close = pd.Series([100.0] * 10)
    volume = pd.Series([1000] * 10)
    result = _obv(close, volume)
    assert (result == 0).all()


def make_ohlcv(n: int, seed: int = 42) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with n business days.

    Uses a geometric random walk so the data looks realistic but is fully
    reproducible.  n must be > 252 for any output rows to survive dropna().
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = close * (1 + rng.uniform(0, 0.02, n))
    low = close * (1 - rng.uniform(0, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.integers(1_000_000, 10_000_000, n).astype(int)
    return pd.DataFrame(
        {
            "symbol": "TEST",
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.fixture(scope="module")
def full_df():
    """400-bar OHLCV series.  Module-scoped so it's built once for all tests."""
    return make_ohlcv(400)


def test_no_lookahead_bias(full_df):
    """
    Feature values for a given date must be identical whether we compute
    them on a dataset that ends on that date or on a longer dataset that
    includes future prices.

    A failing assertion here means a rolling window is consuming future data.

    How it works:
      - full_df has 400 bars.  We take the first 300 as the "short" series.
      - The longest rolling window is 252 bars (return_252d / high_52w), so
        both series produce output rows starting at bar 252.
      - The last date in the short result appears in both results — we compare
        every feature value at that date. If future prices leaked in, the
        full-series computation would see different data and produce a
        different number.
    """
    short_df = full_df.iloc[:300].copy()

    full_features = compute_technical_features(full_df)
    short_features = compute_technical_features(short_df)

    shared_dates = set(full_features["date"]) & set(short_features["date"])
    assert shared_dates, (
        "No overlapping dates between the two results.  "
        "Try increasing n in make_ohlcv() so both series have >252 bars of output."
    )
    last_shared = max(shared_dates)

    full_row = full_features[full_features["date"] == last_shared].iloc[0]
    short_row = short_features[short_features["date"] == last_shared].iloc[0]

    numeric_cols = full_features.select_dtypes(include="number").columns
    for col in numeric_cols:
        assert np.isclose(full_row[col], short_row[col], rtol=1e-9), (
            f"Look-ahead bias detected in '{col}' on {last_shared.date()}: "
            f"full={full_row[col]:.8f}, short={short_row[col]:.8f}"
        )


def test_dates_are_a_subset_of_input(full_df):
    """
    Every date in the output must have been present in the input.

    dropna() removes early rows, and reset_index(drop=True) renumbers the
    integer row index.  Neither should shift which date is attached to which
    feature row. A failure here means a date got mis-tagged to a different
    day's prices — a silent but serious data-integrity bug.
    """
    result = compute_technical_features(full_df)
    output_dates = set(result["date"])
    input_dates = set(full_df["date"])
    assert output_dates.issubset(input_dates), (
        f"Output contains dates not in the input: {output_dates - input_dates}"
    )


def test_dates_monotonic_ascending(full_df):
    """Output rows must be ordered oldest-to-newest."""
    result = compute_technical_features(full_df)
    assert result["date"].is_monotonic_increasing, (
        "Dates are not in ascending order after dropna/reset_index."
    )


def test_no_duplicate_dates(full_df):
    """Each date should appear exactly once (one row per trading day)."""
    result = compute_technical_features(full_df)
    duplicates = result[result["date"].duplicated()]["date"]
    assert duplicates.empty, f"Duplicate dates in output: {duplicates.values}"


def test_return_1d_equals_pct_change(full_df):
    """
    return_1d must equal (close_today - close_yesterday) / close_yesterday.

    This is the simplest possible correctness check.  If it fails, something
    is wrong with the column definitions or the input data order.
    """
    result = compute_technical_features(full_df)

    for i in range(10, 15):
        row = result.iloc[i]
        prev = result.iloc[i - 1]
        expected = (row["close"] - prev["close"]) / prev["close"]
        assert np.isclose(row["return_1d"], expected, rtol=1e-9), (
            f"return_1d wrong at row {i}: got {row['return_1d']:.8f}, "
            f"expected {expected:.8f}"
        )


def test_volume_ratio_positive(full_df):
    """volume_ratio = volume / 50d avg volume, always positive for valid data."""
    result = compute_technical_features(full_df)
    valid = result["volume_ratio"].dropna()
    assert (valid > 0).all(), "volume_ratio contains non-positive values."


def test_pct_from_52w_high_non_positive(full_df):
    """pct_from_52w_high = (close - 52w_max) / 52w_max, always <= 0."""
    result = compute_technical_features(full_df)
    violating = result[result["pct_from_52w_high"] > 1e-9]
    assert violating.empty, (
        f"pct_from_52w_high is positive on {len(violating)} rows — "
        "price is above its own rolling max, which is impossible."
    )
