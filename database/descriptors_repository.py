from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

# Schema (the stock_descriptors table) is managed by Alembic — see
# migrations/versions/0001_initial_schema.py. Run `alembic upgrade head`.

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
