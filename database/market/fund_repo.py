from database.db_connection import get_connection
from database.market.db_utils import _insert_ignore
import pandas as pd
from sqlalchemy import text


def create_table():
    with get_connection().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fund_prices (
                ticker          TEXT            NOT NULL,
                date            DATE            NOT NULL,
                open            DOUBLE PRECISION,
                high            DOUBLE PRECISION,
                low             DOUBLE PRECISION,
                close           DOUBLE PRECISION,
                volume          BIGINT,
                closeadj        DOUBLE PRECISION,
                closeunadj      DOUBLE PRECISION,
                lastupdated     DATE,
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_fund_ticker ON fund_prices (ticker);
        """))


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fund_prices CASCADE"))


def insert(df: pd.DataFrame):
    df.to_sql("fund_prices", get_connection(), if_exists="append", index=False, method=_insert_ignore)



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


def get_latest_date(tickers: str | list[str] | None = None) -> pd.DataFrame:
    q = "SELECT ticker, MAX(date) AS latest_date FROM fund_prices"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " WHERE ticker = ANY(:tickers)"
    q += " GROUP BY ticker"
    return pd.read_sql_query(text(q), get_connection(), params=params)
