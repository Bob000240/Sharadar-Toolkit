from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "date",
    "yield_10y", "yield_2y", "yield_curve", "real_yield",
    "cpi_yoy", "unemployment_rate",
    "credit_spread_hy", "credit_spread_ig",
    "vix",
]

_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)

def create_macro_table():
    engine = get_connection()
    query = text("""
        CREATE TABLE IF NOT EXISTS macro_data (
            date DATE PRIMARY KEY,
            yield_10y DOUBLE PRECISION,
            yield_2y DOUBLE PRECISION,
            yield_curve DOUBLE PRECISION,
            real_yield DOUBLE PRECISION,
            cpi_yoy DOUBLE PRECISION,
            unemployment_rate DOUBLE PRECISION,
            credit_spread_hy DOUBLE PRECISION,
            credit_spread_ig DOUBLE PRECISION,
            vix DOUBLE PRECISION
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)

def drop_macro_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS macro_data;"))

def insert_macro(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()
    query = text(f"""
        INSERT INTO macro_data ({_COL_LIST})
        VALUES ({_BIND_LIST})
        ON CONFLICT (date) DO NOTHING;
    """)
    records = df[_COLUMNS].to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(query, records)

def get_latest_macro(signal_day: pd.Timestamp):
    engine = get_connection()
    query = text(f"""
        SELECT {_COL_LIST}
        FROM macro_data
        WHERE date <= :signal_day
        ORDER BY date DESC
        LIMIT 1
    """)
    params = {
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    return pd.read_sql_query(query, engine, params=params)
