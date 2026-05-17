from database.db_connection import get_connection
import pandas as pd

from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text


def create_OHLCV_table():
    engine = get_connection()

    query = """CREATE TABLE IF NOT EXISTS OHLCV_data (
                symbol TEXT NOT NULL,
                date DATE NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume BIGINT,
                PRIMARY KEY (symbol, date));"""

    with engine.begin() as conn:
        conn.execute(text(query))

    
def drop_OHLCV_table():
    engine = get_connection()

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS OHLCV_data;"))

def insert_OHLCV_table(df):
    engine = get_connection()
    query = """INSERT INTO OHLCV_data (
                symbol, date, open, high, low, close, volume
            )
            VALUES (
                :symbol, :date, :open, :high, :low, :close, :volume
            )
            ON CONFLICT (symbol, date) DO NOTHING;"""

    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(text(query), {
                "symbol": row["symbol"],
                "date": row["date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            })


def get_OHLCV(symbol, start_date=None, end_date=None):
    engine = get_connection()

    query = """
        SELECT symbol, date, open, high, low, close, volume
        FROM OHLCV_data
        WHERE symbol = :symbol
    """

    params = {"symbol": symbol}

    if start_date is not None and end_date is not None:
        query += " AND date BETWEEN :start_date AND :end_date"
        params["start_date"] = start_date
        params["end_date"] = end_date

    query += " ORDER BY date ASC;"

    return pd.read_sql_query(text(query), engine, params=params)