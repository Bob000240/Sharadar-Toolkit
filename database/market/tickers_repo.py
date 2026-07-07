from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "ticker",
    "table_code",
    "permaticker",
    "name",
    "exchange",
    "isdelisted",
    "category",
    "cusips",
    "siccode",
    "sicsector",
    "sicindustry",
    "figi",
    "famaindustry",
    "sector",
    "industry",
    "scalemarketcap",
    "scalerevenue",
    "relatedtickers",
    "currency",
    "location",
    "lastupdated",
    "firstadded",
    "firstpricedate",
    "lastpricedate",
    "firstquarter",
    "lastquarter",
    "secfilings",
    "companysite",
]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)
_UPDATE_SET = ", ".join(
    f"{column} = COALESCE(EXCLUDED.{column}, tickers.{column})"
    for column in _COLUMNS
    if column not in ("ticker", "table_code")
)


def create_table():
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS tickers (
                ticker TEXT NOT NULL,
                table_code TEXT NOT NULL,
                permaticker TEXT,
                name TEXT,
                exchange TEXT,
                isdelisted TEXT,
                category TEXT,
                cusips TEXT,
                siccode TEXT,
                sicsector TEXT,
                sicindustry TEXT,
                figi TEXT,
                famaindustry TEXT,
                sector TEXT,
                industry TEXT,
                scalemarketcap TEXT,
                scalerevenue TEXT,
                relatedtickers TEXT,
                currency TEXT,
                location TEXT,
                lastupdated DATE,
                firstadded DATE,
                firstpricedate DATE,
                lastpricedate DATE,
                firstquarter DATE,
                lastquarter DATE,
                secfilings TEXT,
                companysite TEXT,
                PRIMARY KEY (ticker, table_code)
            );
            CREATE INDEX IF NOT EXISTS idx_tickers_sector ON tickers (sector);
        """)
        )


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS tickers CASCADE"))


def insert(df: pd.DataFrame):
    if df.empty:
        return
    df = df.rename(columns={"table": "table_code"})
    frame = df[_COLUMNS].astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO tickers ({_COL_LIST}) VALUES ({_BIND_LIST}) "
                f"ON CONFLICT (ticker, table_code) DO UPDATE SET {_UPDATE_SET}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    table_code: str | None = None,
    is_delisted: bool | None = None,
) -> pd.DataFrame:
    q = "SELECT * FROM tickers WHERE TRUE"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " AND ticker = ANY(:tickers)"
    if table_code is not None:
        params["table_code"] = table_code
        q += " AND table_code = :table_code"
    if is_delisted is not None:
        params["delisted"] = "Y" if is_delisted else "N"
        q += " AND isdelisted = :delisted"
    q += " ORDER BY ticker"
    return pd.read_sql_query(text(q), get_connection(), params=params)
