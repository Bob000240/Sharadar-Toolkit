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
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS fund_prices (
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
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fund_prices CASCADE"))


def insert(df: pd.DataFrame):
    if df.empty:
        return
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO fund_prices ({_COL_LIST}) VALUES ({_BIND_LIST}) "
                f"{CONFLICT}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    q = "SELECT * FROM fund_prices WHERE TRUE"
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
    with get_connection().connect() as conn:
        result = conn.execute(text("SELECT MAX(lastupdated) FROM fund_prices")).scalar()
        return str(result) if result else None
