from database.db_connection import get_connection
from database.market.db_utils import _insert_ignore
import pandas as pd
from sqlalchemy import text


def create_table():
    with get_connection().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                ticker      TEXT NOT NULL,
                date        DATE NOT NULL,
                eventcodes  TEXT,
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_events_date ON events (date);
        """))


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS events CASCADE"))


def insert(df: pd.DataFrame):
    df.to_sql("events", get_connection(), if_exists="append", index=False, method=_insert_ignore)
    

def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    q = "SELECT * FROM events WHERE TRUE"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " AND ticker = ANY(:tickers)"
    if start_date is not None:
        params["start"] = start_date
        q += " AND date >= :start"
    if end_date is not None:
        params["end"] = end_date
        q += " AND date <= :end"
    q += " ORDER BY ticker, date"
    return pd.read_sql_query(text(q), get_connection(), params=params)


def get_upcoming_earnings(tickers: str | list[str], days_ahead: int = 7) -> pd.DataFrame:
    """Returns tickers with an earnings event (code 22) within the next N days."""
    params = {
        "tickers": [tickers] if isinstance(tickers, str) else tickers,
        "days": days_ahead,
    }
    q = text("""
        SELECT ticker, date, eventcodes
        FROM events
        WHERE ticker = ANY(:tickers)
          AND date BETWEEN CURRENT_DATE AND CURRENT_DATE + :days
          AND eventcodes LIKE '%22%'
        ORDER BY date
    """)
    return pd.read_sql_query(q, get_connection(), params=params)
