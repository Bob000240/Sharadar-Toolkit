"""Persistence for insider transaction filings, one row per disclosed trade.

Filters run on ``filingdate`` rather than ``transactiondate``: a trade is not
knowable until it is disclosed, whatever day it was executed.
"""

from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "ticker",
    "filingdate",
    "formtype",
    "rownum",
    "issuername",
    "ownername",
    "officertitle",
    "isdirector",
    "isofficer",
    "istenpercentowner",
    "transactiondate",
    "transactioncode",
    "transactionshares",
    "transactionpricepershare",
    "transactionvalue",
    "sharesownedbeforetransaction",
    "sharesownedfollowingtransaction",
    "securitytitle",
    "securityadcode",
    "directorindirect",
    "natureofownership",
    "dateexercisable",
    "expirationdate",
    "priceexercisable",
]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)

KEY_COLUMNS = ("ticker", "filingdate", "formtype", "ownername", "rownum")
_NON_PK = [c for c in _COLUMNS if c not in KEY_COLUMNS]
_UPDATE_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in _NON_PK)

CONFLICT = f"ON CONFLICT ({', '.join(KEY_COLUMNS)}) DO UPDATE SET {_UPDATE_SET}"


def create_table():
    """Create the ``insider_transactions`` table and its indexes if absent.

    Idempotent, so setup can be re-run safely.
    """
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS insider_transactions (
                ticker TEXT NOT NULL,
                filingdate DATE NOT NULL,
                formtype TEXT NOT NULL,
                rownum INTEGER NOT NULL,
                issuername TEXT,
                ownername TEXT NOT NULL,
                officertitle TEXT,
                isdirector TEXT,
                isofficer TEXT,
                istenpercentowner TEXT,
                transactiondate DATE,
                transactioncode TEXT,
                transactionshares DOUBLE PRECISION,
                transactionpricepershare DOUBLE PRECISION,
                transactionvalue DOUBLE PRECISION,
                sharesownedbeforetransaction DOUBLE PRECISION,
                sharesownedfollowingtransaction DOUBLE PRECISION,
                securitytitle TEXT,
                securityadcode TEXT,
                directorindirect TEXT,
                natureofownership TEXT,
                dateexercisable DATE,
                expirationdate DATE,
                priceexercisable DOUBLE PRECISION,
                PRIMARY KEY (ticker, filingdate, formtype, ownername, rownum)
            );
            CREATE INDEX IF NOT EXISTS idx_insider_filingdate ON insider_transactions (filingdate);
        """)
        )


def drop_table():
    """Drop ``insider_transactions`` and everything depending on it."""
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS insider_transactions CASCADE"))


def insert(df: pd.DataFrame):
    """Upsert rows into ``insider_transactions``.

    Keyed on ticker, filing date, owner, transaction date, and transaction code.
    Columns outside ``_COLUMNS`` are ignored and NaN/NaT become SQL NULL. A
    duplicate filing is discarded rather than overwritten. No-op on an empty frame.
    """
    if df.empty:
        return
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO insider_transactions ({_COL_LIST}) "
                f"VALUES ({_BIND_LIST}) {CONFLICT}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return ``insider_transactions`` rows matching the supplied filters.

    Every argument is optional and omitting all of them returns the whole
    table. Dates bound ``filingdate`` inclusively, which is the point-in-time
    bound: a filing is invisible before the day it appeared. Ordered by ticker
    then filing date.
    """
    q = "SELECT * FROM insider_transactions WHERE TRUE"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " AND ticker = ANY(:tickers)"
    if start_date is not None:
        params["start"] = start_date
        q += " AND filingdate >= :start"
    if end_date is not None:
        params["end"] = end_date
        q += " AND filingdate <= :end"
    q += " ORDER BY ticker, filingdate"
    return pd.read_sql_query(text(q), get_connection(), params=params)
