import pandas as pd
import pandas_ta as ta


def compute_indicators(df: pd.DataFrame):
    df = df.copy()

    df["return_1d"] = df["close"].pct_change()
    df["return_5d"] = df["close"].pct_change(5)
    df["return_20d"] = df["close"].pct_change(20)
    df["return_60d"] = df["close"].pct_change(60)
    df["return_252d"] = df["close"].pct_change(252)

    df["volatility_20"] = df["return_1d"].rolling(20).std()

    # Moving averages
    df["sma_20"] = ta.sma(df["close"], length=20)
    df["sma_50"] = ta.sma(df["close"], length=50)
    df["sma_200"] = ta.sma(df["close"], length=200)
    df["above_sma_200"] = (
        df["close"].notna() & df["sma_200"].notna() & (df["close"] > df["sma_200"])
    )

    # Relative volume
    df["volume_sma_10"] = ta.sma(df["volume"], length=10)
    df["volume_sma_50"] = ta.sma(df["volume"], length=50)
    df["volume_ratio"] = df["volume_sma_10"] / df["volume_sma_50"]

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

    # Volatility
    df["volatility_20"] = df["return_1d"].rolling(20).std()

    # high
    df["high_52"] = df["high"].rolling(252).max()

    # volume based
    df["obv"] = ta.obv(df["close"], df["volume"])
    df["dollar_volume"] = df["close"] * df["volume"]
    df["dollar_volume_20d_avg"] = df["dollar_volume"].rolling(20).mean()

    df = df.dropna().reset_index(drop=True)

    return df
