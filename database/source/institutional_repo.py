"""Persistence for institutional ownership summarised by ticker.

SHARADAR/SF3A: one row per ticker per quarter, holding counts, share counts and
dollar values split by security type. Summarised rather than per-investor, so a
row lines up with everything else the research layer joins on a ticker.

13F filings appear up to 45 days after the quarter they report on, so a caller
must apply its own filing-delay assumption before treating a quarter as known.
``units`` are shares and ``value`` dollars, rescaled by the load from the
thousands and millions SF3A serves.
"""

from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

SECURITY_TYPES = ("shr", "cll", "put", "wnt", "dbt", "prf", "fnd", "und")

_COUNT_COLUMNS = [f"{kind}holders" for kind in SECURITY_TYPES]
_AMOUNT_COLUMNS = [
    *[f"{kind}units" for kind in SECURITY_TYPES],
    *[f"{kind}value" for kind in SECURITY_TYPES],
    "totalvalue",
    "percentoftotal",
]
_COLUMNS = ["ticker", "date", "name", *_COUNT_COLUMNS, *_AMOUNT_COLUMNS]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)
KEY_COLUMNS = ("ticker", "date")
_NON_PK = [c for c in _COLUMNS if c not in KEY_COLUMNS]
_UPDATE_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in _NON_PK)

CONFLICT = f"ON CONFLICT (ticker, date) DO UPDATE SET {_UPDATE_SET}"

_DEFINITIONS = ",\n                ".join(
    [
        "ticker TEXT NOT NULL",
        "date DATE NOT NULL",
        "name TEXT",
        *[f"{c} INTEGER" for c in _COUNT_COLUMNS],
        *[f"{c} DOUBLE PRECISION" for c in _AMOUNT_COLUMNS],
    ]
)


def create_table():
    """Create the ``institutional_ownership`` table and its index if absent.

    Idempotent, so setup can be re-run safely.
    """
    with get_connection().begin() as conn:
        conn.execute(
            text(f"""
            CREATE TABLE IF NOT EXISTS institutional_ownership (
                {_DEFINITIONS},
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_institutional_ownership_date
                ON institutional_ownership (date);
        """)
        )


def drop_table():
    """Drop ``institutional_ownership`` and everything depending on it."""
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS institutional_ownership CASCADE"))


def insert(df: pd.DataFrame):
    """Upsert rows into ``institutional_ownership``, keyed on ``(ticker, date)``.

    Columns outside ``_COLUMNS`` are ignored and NaN/NaT become SQL NULL. A
    restated quarter overwrites the stored one. No-op on an empty frame.
    """
    if df.empty:
        return
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO institutional_ownership ({_COL_LIST}) "
                f"VALUES ({_BIND_LIST}) {CONFLICT}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return ``institutional_ownership`` rows matching the supplied filters.

    Every argument is optional and omitting all of them returns the whole table.
    Dates bound ``date``, the quarter reported on, not the filing date. Ordered
    by ticker then quarter.
    """
    q = "SELECT * FROM institutional_ownership WHERE TRUE"
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


def get_sync_cursor() -> str | None:
    """Return the newest quarter on record, or None if empty.

    The incremental-load watermark. A quarter rather than the ``lastupdated``
    stamp the other repositories resume from, since SF3A carries no such stamp,
    and re-exported inclusively because the newest quarter is still filling in.
    """
    with get_connection().connect() as conn:
        result = conn.execute(
            text("SELECT MAX(date) FROM institutional_ownership")
        ).scalar()
        return str(result) if result else None
