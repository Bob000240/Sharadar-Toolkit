import pandas as pd
import pandas_ta as ta
import numpy as np


def compute_indicators(df: pd.DataFrame):
    df = df.copy()

    df["return_1d"] = df["close"].pct_change()
    df["return_5d"] = df["close"].pct_change(5)
    df["return_20d"] = df["close"].pct_change(20)
    df["return_60d"] = df["close"].pct_change(60)
    df["return_252d"] = df["close"].pct_change(252)

    # Moving averages
    df["sma_20"] = ta.sma(df["close"], length=20)
    df["sma_50"] = ta.sma(df["close"], length=50)
    df["sma_200"] = ta.sma(df["close"], length=200)
    df["pct_from_sma_20"] = (df["close"] - df["sma_20"]) / df["sma_20"]
    df["pct_from_sma_50"] = (df["close"] - df["sma_50"]) / df["sma_50"]

    # EMAs and crossover
    df["ema_9"] = ta.ema(df["close"], length=9)
    df["ema_21"] = ta.ema(df["close"], length=21)
    df["ema_9_above_21"] = df["ema_9"] > df["ema_21"]
    seq = pd.Series(range(len(df)), index=df.index, dtype=float)
    cross_flags = df["ema_9_above_21"].astype(float).diff().abs() > 0
    df["ema_crossover_days_ago"] = (seq - seq.where(cross_flags).ffill())

    # Relative volume
    df["volume_sma_10"] = ta.sma(df["volume"], length=10)
    df["volume_sma_50"] = ta.sma(df["volume"], length=50)
    df["volume_ratio"] = np.where(
        df["volume_sma_50"] != 0,
        df["volume"] / df["volume_sma_50"],
        np.nan,
    )

    # RSI
    df["rsi_14"] = ta.rsi(df["close"], length=14)

    # MACD
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"] = macd["MACDh_12_26_9"]

    # ATR
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    df["atr_pct"] = df["atr_14"] / df["close"]
    df["consolidation_tightness"] = df["close"].rolling(10).std() / df["atr_14"]

    # Volatility
    df["volatility_20"] = df["return_1d"].rolling(20).std()

    # Vol-adjusted momentum
    df["vol_adjusted_momentum"] = df["return_60d"] / (df["volatility_20"] * np.sqrt(60))

    # high
    df["high_52w"] = df["close"].rolling(252).max()
    df["pct_from_52w_high"] = (df["close"] - df["high_52w"]) / df["high_52w"]
    df["new_52w_high"] = df["close"] >= df["high_52w"]

    # volume based
    df["obv"] = ta.obv(df["close"], df["volume"])
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

    df["slope_x_r2"] = df["trend_slope_60d"] * df["r_squared_60d"]

    # Drawdown / breakout from recent high
    df["rolling_20d_high"] = df["close"].rolling(20).max()
    df["drawdown_from_recent_high"] = (df["close"] - df["rolling_20d_high"]) / df["rolling_20d_high"]
    df["price_vs_20d_high"] = df["drawdown_from_recent_high"]  # 0 = at high = breakout zone

    # Acceleration
    df["momentum_accel_20_60"] = df["return_20d"] - df["return_60d"]
    df["momentum_accel_5_20"] = df["return_5d"] - df["return_20d"]

    return df.reset_index(drop=True)
