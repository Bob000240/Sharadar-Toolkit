from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text


def create_OHLCV_table():
    engine = get_connection()

    query = text("""
        CREATE TABLE IF NOT EXISTS OHLCV_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            PRIMARY KEY (symbol, date)
        );
    """)

    with engine.begin() as conn:
        conn.execute(query)


def drop_OHLCV_table():
    engine = get_connection()

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS OHLCV_data;"))


def insert_OHLCV_table(df: pd.DataFrame):
    engine = get_connection()

    query = text("""
        INSERT INTO OHLCV_data (
            symbol, date, open, high, low, close, volume
        )
        VALUES (
            :symbol, :date, :open, :high, :low, :close, :volume
        )
        ON CONFLICT (symbol, date) DO NOTHING;
    """)

    records = df.to_dict(orient="records")

    with engine.begin() as conn:
        conn.execute(query, records)


def get_OHLCV(
    symbol: str | list[str],
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
):
    engine = get_connection()

    symbols = [symbol] if isinstance(symbol, str) else symbol

    query = """
        SELECT symbol, date, open, high, low, close, volume
        FROM OHLCV_data
        WHERE symbol = ANY(:symbols)
    """

    params = {"symbols": symbols}

    if start_date is not None and end_date is not None:
        query += " AND date BETWEEN :start_date AND :end_date"
        params["start_date"] = start_date
        params["end_date"] = end_date

    query += " ORDER BY date ASC;"

    return pd.read_sql_query(text(query), engine, params=params)


def get_latest_OHLCV(symbol: str, date: pd.Timestamp):
    engine = get_connection()

    query = """
        SELECT symbol, date, open, high, low, close, volume
        FROM OHLCV_data
        WHERE symbol = :symbol 
            AND date <= :date
        ORDER BY date DESC
        LIMIT 1;
    """

    params = {"symbol": symbol, "date": date}

    return pd.read_sql_query(text(query), engine, params=params)
