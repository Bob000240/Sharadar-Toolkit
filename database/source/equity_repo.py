"""Persistence for daily equity OHLCV bars.

Prices are restated as splits and dividends are applied, so an existing bar is
overwritten rather than kept. That is also why a re-adjusted ticker invalidates
its whole derived feature history rather than just its recent rows.
"""

from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "closeadj",
    "closeunadj",
    "lastupdated",
]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)
KEY_COLUMNS = ("ticker", "date")
_NON_PK = [c for c in _COLUMNS if c not in KEY_COLUMNS]
_UPDATE_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in _NON_PK)

CONFLICT = f"ON CONFLICT (ticker, date) DO UPDATE SET {_UPDATE_SET}"


def create_table():
    """Create the ``equity_prices`` table and its indexes if absent.

    Idempotent, so setup can be re-run safely.
    """
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS equity_prices (
                ticker TEXT NOT NULL,
                date DATE NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume DOUBLE PRECISION,
                closeadj DOUBLE PRECISION,
                closeunadj DOUBLE PRECISION,
                lastupdated DATE,
                PRIMARY KEY (ticker, date)
            );
        """)
        )


def drop_table():
    """Drop ``equity_prices`` and everything depending on it."""
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS equity_prices CASCADE"))


def insert(df: pd.DataFrame):
    """Upsert rows into ``equity_prices``, keyed on ``(ticker, date)``.

    Columns outside ``_COLUMNS`` are ignored and NaN/NaT become SQL NULL. A restated bar overwrites the stored one, since Sharadar re-adjusts prices for splits and dividends after the fact. No-op on an empty frame.
    """
    if df.empty:
        return
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO equity_prices ({_COL_LIST}) VALUES ({_BIND_LIST}) "
                f"{CONFLICT}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return ``equity_prices`` rows matching the supplied filters.

    Every argument is optional and omitting all of them returns the whole table. Dates bound the ``date`` column inclusively. Ordered by ticker then date.
    """
    q = "SELECT * FROM equity_prices WHERE TRUE"
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


def get_latest_dates(tickers: str | list[str] | None = None) -> pd.DataFrame:
    """Return the newest stored bar date per ticker.

    Used to work out how far behind each ticker's history has fallen.
    """
    q = "SELECT ticker, MAX(date) AS latest_date FROM equity_prices"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " WHERE ticker = ANY(:tickers)"
    q += " GROUP BY ticker"
    return pd.read_sql_query(text(q), get_connection(), params=params)


def get_sync_cursor() -> str | None:
    """Return the newest ``lastupdated`` stamp on record, or None if empty.

    The incremental-load watermark: the daily update asks the vendor only for rows
    changed since this, so a full refetch is never needed.
    """
    with get_connection().connect() as conn:
        result = conn.execute(
            text("SELECT MAX(lastupdated) FROM equity_prices")
        ).scalar()
        return str(result) if result else None
