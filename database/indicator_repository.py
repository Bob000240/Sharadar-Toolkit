from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import  text

def create_indicators_table():
    engine = get_connection()

    query = """
        CREATE TABLE IF NOT EXISTS indicators_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            return_1d DOUBLE PRECISION,
            return_5d DOUBLE PRECISION,
            return_20d DOUBLE PRECISION,
            sma_20 DOUBLE PRECISION,
            sma_50 DOUBLE PRECISION,
            volume_sma_10 DOUBLE PRECISION,
            volume_sma_50 DOUBLE PRECISION,
            volume_ratio DOUBLE PRECISION,
            rsi_14 DOUBLE PRECISION,
            macd DOUBLE PRECISION,
            macd_signal DOUBLE PRECISION,
            macd_hist DOUBLE PRECISION,
            volatility_20 DOUBLE PRECISION,
            PRIMARY KEY (symbol, date)
        );
    """

    with engine.begin() as conn:
        conn.execute(text(query))

def drop_indicators_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS indicators_data;"))

def insert_indicators(df):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()

    query = """INSERT INTO indicators_data (
                symbol, date, return_1d, return_5d, return_20d,
                sma_20, sma_50, volume_sma_10, volume_sma_50, volume_ratio,
                rsi_14, macd, macd_signal, macd_hist, volatility_20
            )
            VALUES (
                :symbol, :date, :return_1d, :return_5d, :return_20d,
                :sma_20, :sma_50, :volume_sma_10, :volume_sma_50, :volume_ratio,
                :rsi_14, :macd, :macd_signal, :macd_hist, :volatility_20
            )
            ON CONFLICT (symbol, date) DO NOTHING;"""

    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(text(query), {
                "symbol": row["symbol"],
                "date": row["date"],
                "return_1d": row["return_1d"],
                "return_5d": row["return_5d"],
                "return_20d": row["return_20d"],
                "sma_20": row["sma_20"],
                "sma_50": row["sma_50"],
                "volume_sma_10": row["volume_sma_10"],
                "volume_sma_50": row["volume_sma_50"],
                "volume_ratio": row["volume_ratio"],
                "rsi_14": row["rsi_14"],
                "macd": row["macd"],
                "macd_signal": row["macd_signal"],
                "macd_hist": row["macd_hist"],
                "volatility_20": row["volatility_20"],
            })

def get_indicators(symbol, start_date=None, end_date=None):
    engine = get_connection()

    query = """
        SELECT symbol, date, return_1d, return_5d, return_20d,
               sma_20, sma_50, volume_sma_10, volume_sma_50, volume_ratio,
               rsi_14, macd, macd_signal, macd_hist, volatility_20
        FROM indicators_data
        WHERE symbol = :symbol
    """

    params = {"symbol": symbol}

    if start_date is not None and end_date is not None:
        query += " AND date BETWEEN :start_date AND :end_date"
        params["start_date"] = start_date
        params["end_date"] = end_date

    query += " ORDER BY date ASC;"

    return pd.read_sql_query(text(query), engine, params=params)
