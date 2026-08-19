"""Persistence for 13F institutional holdings, one row per investor per quarter.

Holdings are reported quarterly and filed weeks later, so a caller reading these
must apply its own filing-delay assumption before treating a quarter as known.
"""

from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "ticker",
    "investorname",
    "calendardate",
    "value",
    "units",
    "price",
    "securitytype",
]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)
KEY_COLUMNS = ("ticker", "investorname", "calendardate", "securitytype")
_UPDATE_SET = ", ".join(
    f"{column} = EXCLUDED.{column}" for column in _COLUMNS if column not in KEY_COLUMNS
)

CONFLICT = f"ON CONFLICT ({', '.join(KEY_COLUMNS)}) DO UPDATE SET {_UPDATE_SET}"


def create_table():
    """Create the ``institutional_holdings`` table and its indexes if absent.

    Idempotent, so setup can be re-run safely.
    """
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS institutional_holdings (
                ticker TEXT,
                investorname TEXT,
                calendardate DATE,
                value DOUBLE PRECISION,
                units DOUBLE PRECISION,
                price DOUBLE PRECISION,
                securitytype TEXT,
                PRIMARY KEY (ticker, investorname, calendardate, securitytype)
            );
            CREATE INDEX IF NOT EXISTS idx_institutional_date ON institutional_holdings (calendardate);
        """)
        )


def drop_table():
    """Drop ``institutional_holdings`` and everything depending on it."""
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS institutional_holdings CASCADE"))


def insert(df: pd.DataFrame):
    """Upsert rows into ``institutional_holdings``, keyed on ``(ticker,
    investorname, calendardate, securitytype)``.

    Columns outside ``_COLUMNS`` are ignored and NaN/NaT become SQL NULL. A
    restated holding overwrites the stored one. No-op on an empty frame.
    """
    if df.empty:
        return
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO institutional_holdings ({_COL_LIST}) "
                f"VALUES ({_BIND_LIST}) "
                f"{CONFLICT}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return ``institutional_holdings`` rows matching the supplied filters.

    Every argument is optional and omitting all of them returns the whole
    table. Dates bound ``calendardate``, the quarter reported on, not the
    filing date. Ordered by ticker then calendar date.
    """
    q = "SELECT * FROM institutional_holdings WHERE TRUE"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " AND ticker = ANY(:tickers)"
    if start_date is not None:
        params["start"] = start_date
        q += " AND calendardate >= :start"
    if end_date is not None:
        params["end"] = end_date
        q += " AND calendardate <= :end"
    q += " ORDER BY ticker, calendardate"
    return pd.read_sql_query(text(q), get_connection(), params=params)
