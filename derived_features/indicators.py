import pandas as pd
import pandas_ta as ta

def compute_trading_indicators(df):
    df = df.copy()
    df = df.sort_values("date").reset_index(drop=True)
    # Returns
    df["return_1d"] = df["close"].pct_change()
    df["return_5d"] = df["close"].pct_change(5)
    df["return_20d"] = df["close"].pct_change(20)

    # Moving averages
    df["sma_20"] = ta.sma(df["close"], length=20)
    df["sma_50"] = ta.sma(df["close"], length=50)

    # Relative volume
    df["volume_sma_10"] = ta.sma(df["volume"], length=10)
    df["volume_sma_50"] = ta.sma(df["volume"], length=50)
    df["volume_ratio"] = df["volume_sma_10"] / df["volume_sma_50"]

    # RSI
    df["rsi_14"] = ta.rsi(df["close"], length=14)

    # MACD
    macd = ta.macd(df["close"])
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"] = macd["MACDh_12_26_9"]

    # Volatility
    df["volatility_20"] = df["return_1d"].rolling(20).std()

    return df