from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = ["ticker", "investorname", "calendardate", "value", "units", "price", "securitytype"]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_table():
    with get_connection().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS institutional_holdings (
                ticker          TEXT,
                investorname    TEXT,
                calendardate    DATE,
                value           DOUBLE PRECISION,
                units           DOUBLE PRECISION,
                price           DOUBLE PRECISION,
                securitytype    TEXT,
                infoaccuracy    TEXT,
                lastupdated     DATE,
                PRIMARY KEY (ticker, investorname, calendardate, securitytype)
            );
            CREATE INDEX IF NOT EXISTS idx_institutional_ticker ON institutional_holdings (ticker);
            CREATE INDEX IF NOT EXISTS idx_institutional_date ON institutional_holdings (calendardate);
        """))


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS institutional_holdings CASCADE"))


def insert(df: pd.DataFrame):
    if df.empty:
        return
    records = df[_COLUMNS].where(pd.notnull(df[_COLUMNS]), None).to_dict(orient="records")
    records = [{k: None if v is pd.NaT else v for k, v in r.items()} for r in records]
    with get_connection().begin() as conn:
        conn.execute(
            text(f"INSERT INTO institutional_holdings ({_COL_LIST}) VALUES ({_BIND_LIST}) ON CONFLICT DO NOTHING"),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
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


def get_latest_date(tickers: str | list[str] | None = None) -> pd.DataFrame:
    q = "SELECT ticker, MAX(calendardate) AS latest_date FROM institutional_holdings"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " WHERE ticker = ANY(:tickers)"
    q += " GROUP BY ticker"
    return pd.read_sql_query(text(q), get_connection(), params=params)
