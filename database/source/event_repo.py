"""Persistence for corporate event codes, one row per ticker per date.

``eventcodes`` is a pipe-delimited string of Sharadar 8-K codes rather than one
row per code, so membership tests split it on read.
"""

from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = ["ticker", "date", "eventcodes"]
_COL_LIST = ", ".join(_COLUMNS)

CONFLICT = "ON CONFLICT DO NOTHING"
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_table():
    """Create the ``events`` table and its indexes if absent.

    Idempotent, so setup can be re-run safely.
    """
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS events (
                ticker TEXT NOT NULL,
                date DATE NOT NULL,
                eventcodes TEXT,
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_events_date ON events (date);
        """)
        )


def drop_table():
    """Drop ``events`` and everything depending on it."""
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS events CASCADE"))


def insert(df: pd.DataFrame):
    """Upsert rows into ``events``, keyed on ``(ticker, date)``.

    Columns outside ``_COLUMNS`` are ignored and NaN/NaT become SQL NULL. A
    duplicate is discarded rather than overwritten, since an event that already
    landed does not change. No-op on an empty frame.
    """
    if df.empty:
        return
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(f"INSERT INTO events ({_COL_LIST}) VALUES ({_BIND_LIST}) {CONFLICT}"),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return ``events`` rows matching the supplied filters.

    Every argument is optional and omitting all of them returns the whole
    table. Dates bound the ``date`` column inclusively. Ordered by ticker then
    date.
    """
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
