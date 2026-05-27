from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text, bindparam

_COLUMNS = [
    "symbol", "date",
    # Quality
    "roe", "roic", "gross_margin", "operating_margin", "fcf_margin",
    "cash_conversion", "accruals_ratio", "debt_to_equity", "interest_coverage",
    # Value
    "pe_ratio", "forward_pe", "peg_ratio", "pb_ratio", "ev_ebitda",
    "price_to_fcf", "fcf_yield", "earnings_yield", "dividend_yield", "buyback_yield",
    # Growth
    "revenue_ttm", "revenue_growth_yoy", "revenue_growth_qoq",
    "eps_ttm", "eps_growth_yoy", "eps_growth_qoq",
    "revenue_vs_sector_growth", "eps_revision_3m", "growth_consistency_score",
]

_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_fundamentals_table():
    engine = get_connection()
    query = text("""
        CREATE TABLE IF NOT EXISTS fundamentals_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            roe DOUBLE PRECISION,
            roic DOUBLE PRECISION,
            gross_margin DOUBLE PRECISION,
            operating_margin DOUBLE PRECISION,
            fcf_margin DOUBLE PRECISION,
            cash_conversion DOUBLE PRECISION,
            accruals_ratio DOUBLE PRECISION,
            debt_to_equity DOUBLE PRECISION,
            interest_coverage DOUBLE PRECISION,
            pe_ratio DOUBLE PRECISION,
            forward_pe DOUBLE PRECISION,
            peg_ratio DOUBLE PRECISION,
            pb_ratio DOUBLE PRECISION,
            ev_ebitda DOUBLE PRECISION,
            price_to_fcf DOUBLE PRECISION,
            fcf_yield DOUBLE PRECISION,
            earnings_yield DOUBLE PRECISION,
            dividend_yield DOUBLE PRECISION,
            buyback_yield DOUBLE PRECISION,
            revenue_ttm DOUBLE PRECISION,
            revenue_growth_yoy DOUBLE PRECISION,
            revenue_growth_qoq DOUBLE PRECISION,
            eps_ttm DOUBLE PRECISION,
            eps_growth_yoy DOUBLE PRECISION,
            eps_growth_qoq DOUBLE PRECISION,
            revenue_vs_sector_growth DOUBLE PRECISION,
            eps_revision_3m DOUBLE PRECISION,
            growth_consistency_score DOUBLE PRECISION,
            PRIMARY KEY (symbol, date)
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)


def drop_fundamentals_table():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fundamentals_data;"))


def insert_fundamentals(df: pd.DataFrame):
    df = df.where(pd.notnull(df), None)
    engine = get_connection()
    query = text(f"""
        INSERT INTO fundamentals_data ({_COL_LIST})
        VALUES ({_BIND_LIST})
        ON CONFLICT (symbol, date) DO NOTHING;
    """)
    records = df[_COLUMNS].to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(query, records)


def get_latest_fundamentals(symbols: str | list[str], signal_day: pd.Timestamp):
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    query = text(f"""
        SELECT DISTINCT ON (symbol) {_COL_LIST}
        FROM fundamentals_data
        WHERE symbol = ANY(:symbols)
            AND date <= :signal_day
        ORDER BY symbol, date DESC
    """)
    params = {
        "symbols": symbols,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    return pd.read_sql_query(query, engine, params=params)
