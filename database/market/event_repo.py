from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = ["ticker", "date", "eventcodes"]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_table():
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS events (
                ticker      TEXT NOT NULL,
                date        DATE NOT NULL,
                eventcodes  TEXT,
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_events_date ON events (date);
        """)
        )


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS events CASCADE"))


def insert(df: pd.DataFrame):
    if df.empty:
        return
    records = (
        df[_COLUMNS].where(pd.notnull(df[_COLUMNS]), None).to_dict(orient="records")
    )
    records = [{k: None if v is pd.NaT else v for k, v in r.items()} for r in records]
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO events ({_COL_LIST}) VALUES ({_BIND_LIST}) ON CONFLICT DO NOTHING"
            ),
            records,
        )


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


def get_upcoming_earnings(
    tickers: str | list[str], days_ahead: int = 7
) -> pd.DataFrame:
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
          AND eventcodes ~ '(^|\|)22(\||$)'
        ORDER BY date
    """)
    return pd.read_sql_query(q, get_connection(), params=params)
