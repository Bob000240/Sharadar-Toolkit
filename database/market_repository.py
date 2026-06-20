from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

# Schema (the ohlcv_data table) is managed by Alembic — see
# migrations/versions/0001_initial_schema.py. Run `alembic upgrade head`.

def insert_OHLCV_table(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
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

    if start_date is not None:
        query += " AND date >= :start_date"
        params["start_date"] = start_date
    if end_date is not None:
        query += " AND date <= :end_date"
        params["end_date"] = end_date

    query += " ORDER BY date ASC;"

    return pd.read_sql_query(text(query), engine, params=params)

def get_latest_date(symbols: str | list[str]) -> pd.DataFrame:
    """Returns DataFrame(symbol, latest_date) — the most recent date in the DB per symbol."""
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    query = text("""
        SELECT symbol, MAX(date) AS latest_date
        FROM OHLCV_data
        WHERE symbol = ANY(:symbols)
        GROUP BY symbol
    """)
    return pd.read_sql_query(query, engine, params={"symbols": symbols})

def get_latest_OHLCV(symbols: str | list[str], signal_day: pd.Timestamp):
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols

    query = """
        SELECT DISTINCT ON (symbol) symbol, date, open, high, low, close, volume
        FROM OHLCV_data
        WHERE symbol = ANY(:symbols)
            AND date <= :signal_day
        ORDER BY symbol, date DESC
    """

    params = {"symbols": symbols, "signal_day": signal_day}

    return pd.read_sql_query(text(query), engine, params=params)
