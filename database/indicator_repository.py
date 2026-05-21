from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text


def create_indicators_table():
    engine = get_connection()
    
    query = text("""
        CREATE TABLE IF NOT EXISTS indicators_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            return_1d DOUBLE PRECISION,
            return_5d DOUBLE PRECISION,
            return_20d DOUBLE PRECISION,
            return_60d DOUBLE PRECISION,
            return_252d DOUBLE PRECISION,
            sma_20 DOUBLE PRECISION,
            sma_50 DOUBLE PRECISION,
            sma_200 DOUBLE PRECISION,
            above_sma_200 BOOLEAN,
            volume_sma_10 DOUBLE PRECISION,
            volume_sma_50 DOUBLE PRECISION,
            volume_ratio DOUBLE PRECISION,
            rsi_14 DOUBLE PRECISION,
            macd DOUBLE PRECISION,
            macd_signal DOUBLE PRECISION,
            macd_hist DOUBLE PRECISION,
            atr_14 DOUBLE PRECISION,
            atr_pct DOUBLE PRECISION,
            volatility_20 DOUBLE PRECISION,
            high_52 DOUBLE PRECISION,
            obv DOUBLE PRECISION,
            dollar_volume DOUBLE PRECISION,
            dollar_volume_20d_avg DOUBLE PRECISION,
            PRIMARY KEY (symbol, date)
        );
    """)

    with engine.begin() as conn:
        conn.execute(query)


def drop_indicators_table():
    engine = get_connection()

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS indicators_data;"))


def insert_indicators(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()

    query = text("""
        INSERT INTO indicators_data (
            symbol, date, return_1d, return_5d, return_20d,
            return_60d, return_252d,
            sma_20, sma_50, sma_200, above_sma_200,
            volume_sma_10, volume_sma_50, volume_ratio,
            rsi_14, macd, macd_signal, macd_hist,
            atr_14, atr_pct, volatility_20,
            high_52, obv, dollar_volume, dollar_volume_20d_avg
        )
        VALUES (
            :symbol, :date, :return_1d, :return_5d, :return_20d,
            :return_60d, :return_252d,
            :sma_20, :sma_50, :sma_200, :above_sma_200,
            :volume_sma_10, :volume_sma_50, :volume_ratio,
            :rsi_14, :macd, :macd_signal, :macd_hist,
            :atr_14, :atr_pct, :volatility_20,
            :high_52, :obv, :dollar_volume, :dollar_volume_20d_avg
        )
        ON CONFLICT (symbol, date) DO NOTHING;
    """)

    records = df.to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(query, records)


def get_indicators(symbol: str | list[str], start_date: pd.Timestamp | None = None, end_date: pd.Timestamp | None = None):
    engine = get_connection()

    symbols = [symbol] if isinstance(symbol, str) else symbol

    query = """
        SELECT symbol, date, return_1d, return_5d, return_20d,
                return_60d, return_252d,
                sma_20, sma_50, sma_200, above_sma_200,
                volume_sma_10, volume_sma_50, volume_ratio,
                rsi_14, macd, macd_signal, macd_hist,
                atr_14, atr_pct, volatility_20,
                high_52, obv, dollar_volume, dollar_volume_20d_avg
        FROM indicators_data
        WHERE symbol = ANY(:symbols)
    """

    params = {"symbols": symbols}

    if start_date is not None and end_date is not None:
        query += " AND date BETWEEN :start_date AND :end_date"
        params["start_date"] = start_date
        params["end_date"] = end_date

    query += " ORDER BY symbol ASC, date ASC;"

    df = pd.read_sql_query(text(query), engine, params=params)
    df["date"] = pd.to_datetime(df["date"])
    return df

def get_latest_indicators(symbol : str, signal_day : pd.Timestamp):
    engine = get_connection()

    query = """
        SELECT symbol, date, return_1d, return_5d, return_20d,
                return_60d, return_252d,
                sma_20, sma_50, sma_200, above_sma_200,
                volume_sma_10, volume_sma_50, volume_ratio,
                rsi_14, macd, macd_signal, macd_hist,
                atr_14, atr_pct, volatility_20,
                high_52, obv, dollar_volume, dollar_volume_20d_avg
        FROM indicators_data
        WHERE symbol = :symbol
          AND date <= :signal_day
        ORDER BY date DESC
        LIMIT 1;
    """

    params = {
        "symbol": symbol,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day
    }

    return pd.read_sql_query(text(query), engine, params=params)