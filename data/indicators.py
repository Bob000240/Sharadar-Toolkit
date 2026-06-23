import pandas as pd
import numpy as np


def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=length - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=length - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
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
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def compute_indicators(df: pd.DataFrame):
    df = df.copy()

    df["return_1d"] = df["close"].pct_change()
    df["return_5d"] = df["close"].pct_change(5)
    df["return_20d"] = df["close"].pct_change(20)
    df["return_60d"] = df["close"].pct_change(60)
    df["return_252d"] = df["close"].pct_change(252)

    # Moving averages
    df["sma_20"] = _sma(df["close"], 20)
    df["sma_50"] = _sma(df["close"], 50)
    df["sma_200"] = _sma(df["close"], 200)
    df["pct_from_sma_20"] = (df["close"] - df["sma_20"]) / df["sma_20"]
    df["pct_from_sma_50"] = (df["close"] - df["sma_50"]) / df["sma_50"]

    # EMAs and crossover
    df["ema_9"] = _ema(df["close"], 9)
    df["ema_21"] = _ema(df["close"], 21)
    seq = pd.Series(range(len(df)), index=df.index, dtype=float)
    cross_flags = (df["ema_9"] > df["ema_21"]).astype(float).diff().abs() > 0
    df["ema_crossover_days_ago"] = seq - seq.where(cross_flags).ffill()

    # Relative volume
    df["volume_sma_10"] = _sma(df["volume"], 10)
    df["volume_sma_50"] = _sma(df["volume"], 50)
    df["volume_ratio"] = np.where(
        df["volume_sma_50"] != 0,
        df["volume"] / df["volume_sma_50"],
        np.nan,
    )

    # RSI
    df["rsi_14"] = _rsi(df["close"], 14)

    # MACD
    macd = _macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"] = macd["MACDh_12_26_9"]

    # ATR
    df["atr_14"] = _atr(df["high"], df["low"], df["close"], 14)
    df["atr_pct"] = df["atr_14"] / df["close"]
    df["consolidation_tightness"] = df["close"].rolling(10).std() / df["atr_14"]

    # Volatility
    df["volatility_20"] = df["return_1d"].rolling(20).std()

    # Vol-adjusted momentum
    df["vol_adjusted_momentum"] = df["return_60d"] / (df["volatility_20"] * np.sqrt(60))

    # 52-week high
    df["high_52w"] = df["close"].rolling(252).max()
    df["pct_from_52w_high"] = (df["close"] - df["high_52w"]) / df["high_52w"]

    # Volume based
    df["obv"] = _obv(df["close"], df["volume"])
    df["dollar_volume"] = df["close"] * df["volume"]
    df["dollar_volume_20d_avg"] = df["dollar_volume"].rolling(20).mean()

    # Trend quality
    df["r_squared_60d"] = (
        df["close"]
        .rolling(60)
        .apply(lambda x: np.corrcoef(np.arange(60), x)[0, 1] ** 2, raw=True)
    )

    df["trend_slope_60d"] = (
        df["close"]
        .rolling(60)
        .apply(
            lambda x: np.polyfit(np.arange(60), x, 1)[0] / x[-1] * 252,
            raw=True,
        )
    )

    # Drawdown / breakout from recent high
    df["rolling_20d_high"] = df["close"].rolling(20).max()
    df["drawdown_from_recent_high"] = (df["close"] - df["rolling_20d_high"]) / df[
        "rolling_20d_high"
    ]

    return df.reset_index(drop=True)
