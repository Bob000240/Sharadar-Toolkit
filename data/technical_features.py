"""Generate daily technical features from ticker OHLCV history."""

import pandas as pd
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def _rolling_trend(close: pd.Series, window: int = 60) -> tuple[pd.Series, pd.Series]:
    """Return the R-squared and annualised slope of a rolling linear fit.

    A closed-form rolling regression of close against time. It replaces a
    per-window ``rolling.apply`` of corrcoef and polyfit, which ran a Python
    callable on every window of every ticker and dominated feature-generation
    runtime.

    Values are identical to the version it replaced: the leading ``window - 1``
    rows and any window containing a NaN are NaN.
    """
    y = close.to_numpy(dtype=float)
    n = y.size
    r2 = np.full(n, np.nan)
    slope = np.full(n, np.nan)
    if n >= window:
        w = sliding_window_view(y, window)
        t = np.arange(window, dtype=float)
        tc = t - t.mean()
        t_ss = float((tc * tc).sum())
        yc = w - w.mean(axis=1, keepdims=True)
        cov_ty = (tc * yc).sum(axis=1)
        y_ss = (yc * yc).sum(axis=1)
        last = w[:, -1]
        with np.errstate(invalid="ignore", divide="ignore"):
            r2[window - 1 :] = np.where(
                y_ss > 0, cov_ty * cov_ty / (t_ss * y_ss), np.nan
            )
            slope[window - 1 :] = (cov_ty / t_ss) / last * 252.0
    return pd.Series(r2, index=close.index), pd.Series(slope, index=close.index)


def _sma(series: pd.Series, length: int) -> pd.Series:
    """Return the simple moving average over ``length`` bars."""
    return series.rolling(length).mean()


def _ema(series: pd.Series, length: int) -> pd.Series:
    """Return the exponential moving average over ``length`` bars."""
    return series.ewm(span=length, adjust=False).mean()


def _rsi(series: pd.Series, length: int) -> pd.Series:
    """Return the Relative Strength Index over ``length`` bars."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=length - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=length - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    """Return the MACD line, its signal line, and their histogram."""
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame(
        {
            f"MACD_{fast}_{slow}_{signal}": macd_line,
            f"MACDs_{fast}_{slow}_{signal}": signal_line,
            f"MACDh_{fast}_{slow}_{signal}": hist,
        }
    )


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """Return the Average True Range over ``length`` bars."""
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=length - 1, adjust=False).mean()


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Return On-Balance Volume, the signed cumulative volume."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def compute_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute every technical feature for one ticker's price history.

    Expects a single ticker's bars sorted by date, because every rolling window
    depends on the full contiguous series. Leading rows are NaN until each window
    fills, which is the honest answer for a security without the history yet.

    Return a copy of ``df`` with the feature columns added and the index reset.
    """
    df = df.copy()

    df["return_1d"] = df["close"].pct_change()
    df["return_5d"] = df["close"].pct_change(5)
    df["return_20d"] = df["close"].pct_change(20)
    df["return_60d"] = df["close"].pct_change(60)
    df["return_252d"] = df["close"].pct_change(252)

    df["sma_20"] = _sma(df["close"], 20)
    df["sma_50"] = _sma(df["close"], 50)
    df["sma_200"] = _sma(df["close"], 200)
    df["pct_from_sma_20"] = (df["close"] - df["sma_20"]) / df["sma_20"]
    df["pct_from_sma_50"] = (df["close"] - df["sma_50"]) / df["sma_50"]
    df["pct_from_sma_200"] = (df["close"] - df["sma_200"]) / df["sma_200"]

    df["ema_9"] = _ema(df["close"], 9)
    df["ema_21"] = _ema(df["close"], 21)
    seq = pd.Series(range(len(df)), index=df.index, dtype=float)
    cross_flags = (df["ema_9"] > df["ema_21"]).astype(float).diff().abs() > 0
    df["ema_crossover_days_ago"] = seq - seq.where(cross_flags).ffill()

    df["volume_sma_10"] = _sma(df["volume"], 10)
    df["volume_sma_50"] = _sma(df["volume"], 50)
    df["volume_ratio"] = np.where(
        df["volume_sma_50"] != 0,
        df["volume"] / df["volume_sma_50"],
        np.nan,
    )

    df["rsi_14"] = _rsi(df["close"], 14)

    macd = _macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"] = macd["MACDh_12_26_9"]

    df["atr_14"] = _atr(df["high"], df["low"], df["close"], 14)
    df["atr_pct"] = df["atr_14"] / df["close"]
    df["consolidation_tightness"] = df["close"].rolling(10).std() / df["atr_14"]

    df["volatility_20"] = df["return_1d"].rolling(20).std()

    df["vol_adjusted_momentum"] = df["return_60d"] / (df["volatility_20"] * np.sqrt(60))

    df["high_52w"] = df["close"].rolling(252).max()
    df["pct_from_52w_high"] = (df["close"] - df["high_52w"]) / df["high_52w"]

    df["obv"] = _obv(df["close"], df["volume"])
    df["dollar_volume"] = df["close"] * df["volume"]
    df["dollar_volume_20d_avg"] = df["dollar_volume"].rolling(20).mean()

    df["r_squared_60d"], df["trend_slope_60d"] = _rolling_trend(df["close"], 60)

    df["rolling_20d_high"] = df["close"].rolling(20).max()
    df["drawdown_from_recent_high"] = (df["close"] - df["rolling_20d_high"]) / df[
        "rolling_20d_high"
    ]

    return df.reset_index(drop=True)
