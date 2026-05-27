from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text, bindparam

_COLUMNS = [
    "symbol", "date",
    "analyst_buy_pct", "analyst_hold_pct", "analyst_sell_pct",
    "analyst_consensus_score",
    "rating_change_direction",
    "price_target_mean", "price_target_high", "price_target_low",
    "news_sentiment_score", "sentiment_trend_20d",
    "short_interest_pct", "short_interest_ratio",
]

_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_sentiment_table():
    engine = get_connection()
    query = text("""
        CREATE TABLE IF NOT EXISTS sentiment_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            analyst_buy_pct DOUBLE PRECISION,
            analyst_hold_pct DOUBLE PRECISION,
            analyst_sell_pct DOUBLE PRECISION,
            analyst_consensus_score DOUBLE PRECISION,
            rating_change_direction TEXT,
            price_target_mean DOUBLE PRECISION,
            price_target_high DOUBLE PRECISION,
            price_target_low DOUBLE PRECISION,
            news_sentiment_score DOUBLE PRECISION,
            sentiment_trend_20d DOUBLE PRECISION,
            short_interest_pct DOUBLE PRECISION,
            short_interest_ratio DOUBLE PRECISION,
            PRIMARY KEY (symbol, date)
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)


def drop_sentiment_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS sentiment_data;"))


def insert_sentiment(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()
    query = text(f"""
        INSERT INTO sentiment_data ({_COL_LIST})
        VALUES ({_BIND_LIST})
        ON CONFLICT (symbol, date) DO NOTHING;
    """)
    records = df[_COLUMNS].to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(query, records)


def get_latest_sentiment(symbols: str | list[str], signal_day: pd.Timestamp):
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    query = text(f"""
        SELECT DISTINCT ON (symbol) {_COL_LIST}
        FROM sentiment_data
        WHERE symbol = ANY(:symbols)
            AND date <= :signal_day
        ORDER BY symbol, date DESC
    """)
    params = {
        "symbols": symbols,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    return pd.read_sql_query(query, engine, params=params)
