from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

def create_sector_mapping_table():
    engine = get_connection()

    query = text("""CREATE TABLE IF NOT EXISTS sector_mapping (
            symbol TEXT PRIMARY KEY,
            sector TEXT,
            industry TEXT);""")

    with engine.begin() as conn:
        conn.execute(query)

def drop_sector_mapping_table():
    engine = get_connection()

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS sector_mapping;"))

def insert_sector_mapping(df : pd.DataFrame):
    engine = get_connection()

    query = text("""INSERT INTO sector_mapping (
            symbol, sector, industry
        )
        VALUES (
            :symbol, :sector, :industry
        )
        ON CONFLICT (symbol) DO UPDATE SET
            sector = EXCLUDED.sector,
            industry = EXCLUDED.industry;""")

    records = df.to_dict(orient="records")

    with engine.begin() as conn:
        conn.execute(query, records)

def get_sector_mapping(symbols : list[str] | str | None = None):
    if isinstance(symbols, str):
        symbols = [symbols]
    engine = get_connection()

    if symbols is not None:
        symbols = [symbols] if isinstance(symbols, str) else list(symbols)
        query = text("""SELECT symbol, sector, industry
            FROM sector_mapping
            WHERE symbol = ANY(:symbols);""")
        params = {"symbols": symbols}
    else:
        query = text("""SELECT symbol, sector, industry
            FROM sector_mapping;""")
        params = {}

    with engine.begin() as conn:
        result = conn.execute(query, params)
        df = pd.DataFrame(result.fetchall(), columns=result.keys())

    return df

