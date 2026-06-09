from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text


def create_descriptors_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_descriptors (
                symbol       TEXT PRIMARY KEY,
                company_name TEXT,
                sector       TEXT,
                industry     TEXT,
                country      TEXT,
                exchange     TEXT,
                currency     TEXT,
                market_cap   NUMERIC,
                size_bucket  TEXT,
                is_etf       BOOLEAN
            );
        """))


def drop_descriptors_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS stock_descriptors;"))


def insert_descriptors(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()
    query = text("""
        INSERT INTO stock_descriptors (
            symbol, company_name, sector, industry,
            country, exchange, currency, market_cap, size_bucket, is_etf
        )
        VALUES (
            :symbol, :company_name, :sector, :industry,
            :country, :exchange, :currency, :market_cap, :size_bucket, :is_etf
        )
        ON CONFLICT (symbol) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            sector       = EXCLUDED.sector,
            industry     = EXCLUDED.industry,
            country      = EXCLUDED.country,
            exchange     = EXCLUDED.exchange,
            currency     = EXCLUDED.currency,
            market_cap   = EXCLUDED.market_cap,
            size_bucket  = EXCLUDED.size_bucket,
            is_etf       = EXCLUDED.is_etf;
    """)
    with engine.begin() as conn:
        conn.execute(query, df.to_dict(orient="records"))


def get_descriptors(symbols: list[str] | str | None = None) -> pd.DataFrame:
    if isinstance(symbols, str):
        symbols = [symbols]
    engine = get_connection()
    if symbols is not None:
        query = text("""
            SELECT symbol, company_name, sector, industry,
                   country, exchange, currency, market_cap, size_bucket, is_etf
            FROM stock_descriptors
            WHERE symbol = ANY(:symbols);
        """)
        params = {"symbols": symbols}
    else:
        query = text("""
            SELECT symbol, company_name, sector, industry,
                   country, exchange, currency, market_cap, size_bucket, is_etf
            FROM stock_descriptors;
        """)
        params = {}
    with engine.begin() as conn:
        result = conn.execute(query, params)
        return pd.DataFrame(result.fetchall(), columns=result.keys())
