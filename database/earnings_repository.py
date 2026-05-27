from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text, bindparam

_COLUMNS = [
    "symbol", "date",
    "next_earnings_date",
    "days_to_earnings",
    "implied_move_pct",
    "estimate_dispersion",
    "eps_surprise_1q", "eps_surprise_2q", "eps_surprise_3q", "eps_surprise_4q",
    "mean_eps_surprise",
    "pead_signal",
    "estimate_revision_direction",
]

_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_earnings_table():
    engine = get_connection()
    query = text("""
        CREATE TABLE IF NOT EXISTS earnings_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            next_earnings_date DATE,
            days_to_earnings INTEGER,
            implied_move_pct DOUBLE PRECISION,
            estimate_dispersion DOUBLE PRECISION,
            eps_surprise_1q DOUBLE PRECISION,
            eps_surprise_2q DOUBLE PRECISION,
            eps_surprise_3q DOUBLE PRECISION,
            eps_surprise_4q DOUBLE PRECISION,
            mean_eps_surprise DOUBLE PRECISION,
            pead_signal TEXT,
            estimate_revision_direction TEXT,
            PRIMARY KEY (symbol, date)
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)


def drop_earnings_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS earnings_data;"))


def insert_earnings(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()
    query = text(f"""
        INSERT INTO earnings_data ({_COL_LIST})
        VALUES ({_BIND_LIST})
        ON CONFLICT (symbol, date) DO NOTHING;
    """)
    records = df[_COLUMNS].to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(query, records)


def get_latest_earnings(symbols: str | list[str], signal_day: pd.Timestamp):
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    query = text(f"""
        SELECT DISTINCT ON (symbol) {_COL_LIST}
        FROM earnings_data
        WHERE symbol = ANY(:symbols)
            AND date <= :signal_day
        ORDER BY symbol, date DESC
    """)
    params = {
        "symbols": symbols,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    return pd.read_sql_query(query, engine, params=params)
