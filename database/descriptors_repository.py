"""
Stock and ETF descriptor table, sourced from Sharadar TICKERS.
Maps Sharadar TICKERS fields to a normalized stock_descriptors schema.
"""
from __future__ import annotations
import pandas as pd
from sqlalchemy import text
from database.db_connection import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS stock_descriptors (
    ticker          VARCHAR(16)  PRIMARY KEY,   -- Sharadar ticker (was 'symbol')
    company_name    TEXT,
    sector          TEXT,
    industry        TEXT,
    sic_sector      TEXT,
    sic_industry    TEXT,
    fama_industry   TEXT,
    country         TEXT,
    exchange        VARCHAR(16),
    currency        VARCHAR(8),
    is_etf          BOOLEAN      NOT NULL DEFAULT FALSE,
    is_delisted     BOOLEAN      NOT NULL DEFAULT FALSE,
    scale_market_cap SMALLINT,          -- 1=Nano 2=Micro 3=Small 4=Mid 5=Large 6=Mega
    scale_revenue   SMALLINT,
    sic_code        VARCHAR(8),
    perma_ticker    VARCHAR(16),
    first_price_date DATE,
    last_price_date  DATE,
    first_quarter   DATE,
    last_quarter    DATE,
    last_updated    DATE
);
"""

# Sharadar TICKERS → our column names
_TICKERS_MAP = {
    "ticker":           "ticker",
    "name":             "company_name",
    "sector":           "sector",
    "industry":         "industry",
    "sicsector":        "sic_sector",
    "sicindustry":      "sic_industry",
    "famaindustry":     "fama_industry",
    "location":         "country",
    "exchange":         "exchange",
    "currency":         "currency",
    "category":         "_category",     # used to derive is_etf
    "isdelisted":       "_isdelisted",   # Y/N string → boolean
    "scalemarketcap":   "scale_market_cap",
    "scalerevenue":     "scale_revenue",
    "siccode":          "sic_code",
    "permaticker":      "perma_ticker",
    "firstpricedate":   "first_price_date",
    "lastpricedate":    "last_price_date",
    "firstquarter":     "first_quarter",
    "lastquarter":      "last_quarter",
    "lastupdated":      "last_updated",
}

_INSERT_COLS = [
    "ticker", "company_name", "sector", "industry", "sic_sector", "sic_industry",
    "fama_industry", "country", "exchange", "currency",
    "is_etf", "is_delisted", "scale_market_cap", "scale_revenue",
    "sic_code", "perma_ticker", "first_price_date", "last_price_date",
    "first_quarter", "last_quarter", "last_updated",
]


def create_descriptors_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL))
        conn.commit()


def drop_descriptors_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS stock_descriptors CASCADE"))
        conn.commit()


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=_TICKERS_MAP)
    # Derive boolean columns from Sharadar string conventions
    if "_isdelisted" in df.columns:
        df["is_delisted"] = df["_isdelisted"].str.upper() == "Y"
    else:
        df["is_delisted"] = False

    if "_category" in df.columns:
        df["is_etf"] = df["_category"].str.contains("ETF|Fund", case=False, na=False)
    else:
        df["is_etf"] = False

    # Keep only insert columns that are present
    present = [c for c in _INSERT_COLS if c in df.columns]
    return df[present].where(pd.notnull(df[present]), None)


def insert_descriptors(df: pd.DataFrame) -> None:
    """Upsert Sharadar TICKERS dataframe (all columns mapped automatically)."""
    df = _prepare(df)
    if df.empty:
        return

    cols = [c for c in _INSERT_COLS if c in df.columns]
    col_list  = ", ".join(cols)
    bind_list = ", ".join(f":{c}" for c in cols)
    non_pk    = [c for c in cols if c != "ticker"]
    update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in non_pk)

    sql = text(f"""
        INSERT INTO stock_descriptors ({col_list})
        VALUES ({bind_list})
        ON CONFLICT (ticker) DO UPDATE SET {update_set}
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, df[cols].to_dict("records"))
        conn.commit()


def get_descriptors(symbols: list[str] | str | None = None) -> pd.DataFrame:
    """Return descriptor rows, optionally filtered by ticker list.

    Returns a 'symbol' alias column so legacy code keeps working.
    """
    if isinstance(symbols, str):
        symbols = [symbols]

    if symbols is not None:
        sql = text("""
            SELECT *, ticker AS symbol FROM stock_descriptors
            WHERE ticker = ANY(:symbols)
        """)
        params = {"symbols": symbols}
    else:
        sql = text("SELECT *, ticker AS symbol FROM stock_descriptors")
        params = {}

    with get_connection().connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return pd.DataFrame(rows)
