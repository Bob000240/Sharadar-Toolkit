from database.db_connection import get_connection
from database.market.db_utils import _insert_ignore
import pandas as pd
from sqlalchemy import text


def create_table():
    with get_connection().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS insider_transactions (
                rownum                          INTEGER         PRIMARY KEY,
                ticker                          TEXT            NOT NULL,
                filingdate                      DATE,
                formtype                        TEXT,
                issuername                      TEXT,
                ownername                       TEXT,
                officertitle                    TEXT,
                isdirector                      TEXT,
                isofficer                       TEXT,
                istenpercentowner               TEXT,
                transactiondate                 DATE,
                transactioncode                 TEXT,
                transactionshares               DOUBLE PRECISION,
                transactionpricepershare        DOUBLE PRECISION,
                transactionvalue                DOUBLE PRECISION,
                sharesownedbeforetransaction    DOUBLE PRECISION,
                sharesownedfollowingtransaction DOUBLE PRECISION,
                securitytitle                   TEXT,
                securityadcode                  TEXT,
                directorindirect                TEXT,
                natureofownership               TEXT,
                dateexercisable                 DATE,
                expirationdate                  DATE,
                priceexercisable                DOUBLE PRECISION
            );
            CREATE INDEX IF NOT EXISTS idx_insider_ticker ON insider_transactions (ticker);
            CREATE INDEX IF NOT EXISTS idx_insider_filingdate ON insider_transactions (filingdate);
        """))


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS insider_transactions CASCADE"))


def insert(df: pd.DataFrame):
    df.to_sql("insider_transactions", get_connection(), if_exists="append", index=False, method=_insert_ignore)


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
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
