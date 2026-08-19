"""Persistence for SHARADAR/DAILY: valuation metrics repriced every session.

One row per ticker per trading day. Each metric pairs the day's price with the
most recent SEC form 10 filing, so the price half is current while the
fundamental half is frozen at the last filing — unlike the SF1 twins of these
columns, whose price is also frozen at the filing date.
"""

from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "ticker",
    "date",
    "lastupdated",
    "ev",
    "evebit",
    "evebitda",
    "marketcap",
    "pb",
    "pe",
    "ps",
]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)
KEY_COLUMNS = ("ticker", "date")
_NON_PK = [c for c in _COLUMNS if c not in KEY_COLUMNS]
_UPDATE_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in _NON_PK)

CONFLICT = f"ON CONFLICT (ticker, date) DO UPDATE SET {_UPDATE_SET}"


def create_table():
    """Create the ``daily_valuation`` table and its indexes if absent.

    Idempotent, so setup can be re-run safely.
    """
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS daily_valuation (
                ticker TEXT NOT NULL,
                date DATE NOT NULL,
                lastupdated DATE,
                ev DOUBLE PRECISION,
                evebit DOUBLE PRECISION,
                evebitda DOUBLE PRECISION,
                marketcap DOUBLE PRECISION,
                pb DOUBLE PRECISION,
                pe DOUBLE PRECISION,
                ps DOUBLE PRECISION,
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_daily_valuation_lastupdated
                ON daily_valuation (lastupdated);
        """)
        )


def drop_table():
    """Drop ``daily_valuation`` and everything depending on it."""
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS daily_valuation CASCADE"))


def insert(df: pd.DataFrame):
    """Upsert rows into ``daily_valuation``, keyed on ``(ticker, date)``.

    Columns outside ``_COLUMNS`` are ignored and NaN/NaT become SQL NULL. A
    revised row overwrites the stored one. No-op on an empty frame.
    """
    if df.empty:
        return
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO daily_valuation ({_COL_LIST}) VALUES ({_BIND_LIST}) "
                f"{CONFLICT}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return ``daily_valuation`` rows matching the supplied filters.

    Every argument is optional and omitting all of them returns the whole
    table. Dates bound the ``date`` column inclusively. Ordered by ticker then
    date.
    """
    q = "SELECT * FROM daily_valuation WHERE TRUE"
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


def get_latest_rows(
    tickers: str | list[str] | None, signal_day: pd.Timestamp
) -> pd.DataFrame:
    """Each ticker's most recent row on or before ``signal_day``.

    Same access pattern as the technical features repo: an explicit ticker list
    drives one index seek per ticker against the (ticker, date) primary key.
    There is no lower date bound, so a long-delisted ticker still resolves to
    its final row.
    """
    signal_day = signal_day.date() if hasattr(signal_day, "date") else signal_day

    if tickers is None:
        return pd.read_sql_query(
            text("""
                SELECT DISTINCT ON (ticker) *
                FROM daily_valuation
                WHERE date <= :signal_day
                ORDER BY ticker, date DESC
            """),
            get_connection(),
            params={"signal_day": signal_day},
        )

    return pd.read_sql_query(
        text("""
            SELECT latest.*
            FROM unnest(CAST(:tickers AS text[])) AS wanted(ticker)
            JOIN LATERAL (
                SELECT *
                FROM daily_valuation AS dv
                WHERE dv.ticker = wanted.ticker
                  AND dv.date <= :signal_day
                ORDER BY dv.date DESC
                LIMIT 1
            ) AS latest ON TRUE
            ORDER BY latest.ticker
        """),
        get_connection(),
        params={
            "tickers": [tickers] if isinstance(tickers, str) else list(tickers),
            "signal_day": signal_day,
        },
    )


def get_sync_cursor() -> str | None:
    """Return the newest ``lastupdated`` stamp on record, or None if empty.

    The incremental-load watermark: the daily update asks the vendor only for rows
    changed since this, so a full refetch is never needed.
    """
    with get_connection().connect() as conn:
        result = conn.execute(
            text("SELECT MAX(lastupdated) FROM daily_valuation")
        ).scalar()
        return str(result) if result else None
