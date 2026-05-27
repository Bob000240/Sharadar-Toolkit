from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text, bindparam

_COLUMNS = [
    "symbol", "date",
    "buys_90d", "sells_90d",
    "buy_value_90d", "sell_value_90d", "net_value_90d",
    "buy_sell_ratio",
    "ceo_buying", "cfo_buying", "cluster_buy_flag",
]

_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_insider_table():
    engine = get_connection()
    query = text("""
        CREATE TABLE IF NOT EXISTS insider_summary (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            buys_90d INTEGER,
            sells_90d INTEGER,
            buy_value_90d DOUBLE PRECISION,
            sell_value_90d DOUBLE PRECISION,
            net_value_90d DOUBLE PRECISION,
            buy_sell_ratio DOUBLE PRECISION,
            ceo_buying BOOLEAN,
            cfo_buying BOOLEAN,
            cluster_buy_flag BOOLEAN,
            PRIMARY KEY (symbol, date)
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)


def drop_insider_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS insider_summary;"))


def insert_insider(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()
    query = text(f"""
        INSERT INTO insider_summary ({_COL_LIST})
        VALUES ({_BIND_LIST})
        ON CONFLICT (symbol, date) DO NOTHING;
    """)
    records = df[_COLUMNS].to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(query, records)


def get_latest_insider(symbols: str | list[str], signal_day: pd.Timestamp):
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    query = text(f"""
        SELECT DISTINCT ON (symbol) {_COL_LIST}
        FROM insider_summary
        WHERE symbol = ANY(:symbols)
            AND date <= :signal_day
        ORDER BY symbol, date DESC
    """)
    params = {
        "symbols": symbols,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    return pd.read_sql_query(query, engine, params=params)
