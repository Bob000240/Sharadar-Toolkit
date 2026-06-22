from database.db_connection import get_connection
from database.market.db_utils import _insert_ignore
import pandas as pd
from sqlalchemy import text


def create_table():
    with get_connection().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS macro (
                date                DATE PRIMARY KEY,

                -- Yields
                yield_1m            DOUBLE PRECISION,
                yield_3m            DOUBLE PRECISION,
                yield_6m            DOUBLE PRECISION,
                yield_1y            DOUBLE PRECISION,
                yield_2y            DOUBLE PRECISION,
                yield_5y            DOUBLE PRECISION,
                yield_10y           DOUBLE PRECISION,
                yield_20y           DOUBLE PRECISION,
                yield_30y           DOUBLE PRECISION,

                -- Real yields (TIPS)
                real_yield_5y       DOUBLE PRECISION,
                real_yield_10y      DOUBLE PRECISION,
                real_yield_20y      DOUBLE PRECISION,

                -- Breakeven inflation
                breakeven_5y        DOUBLE PRECISION,
                breakeven_10y       DOUBLE PRECISION,

                -- Policy rates
                fed_funds_rate      DOUBLE PRECISION,
                sofr                DOUBLE PRECISION,

                -- Credit spreads
                spread_hy           DOUBLE PRECISION,
                spread_ig           DOUBLE PRECISION,
                yield_hy            DOUBLE PRECISION,
                yield_ig            DOUBLE PRECISION,
                ted_spread          DOUBLE PRECISION,

                -- Inflation
                cpi                 DOUBLE PRECISION,
                cpi_core            DOUBLE PRECISION,
                pce                 DOUBLE PRECISION,
                pce_core            DOUBLE PRECISION,
                cpi_yoy             DOUBLE PRECISION,
                cpi_core_yoy        DOUBLE PRECISION,
                pce_yoy             DOUBLE PRECISION,

                -- Labor
                unemployment_rate   DOUBLE PRECISION,
                jobless_claims      DOUBLE PRECISION,
                nonfarm_payrolls    DOUBLE PRECISION,

                -- Activity
                industrial_production DOUBLE PRECISION,
                retail_sales        DOUBLE PRECISION,
                gdp                 DOUBLE PRECISION,

                -- Money supply
                m2                  DOUBLE PRECISION,

                -- Housing
                housing_starts      DOUBLE PRECISION,
                case_shiller_hpi    DOUBLE PRECISION,

                -- Commodities
                oil_wti             DOUBLE PRECISION,
                gold                DOUBLE PRECISION,

                -- Dollar
                dxy                 DOUBLE PRECISION,
                eurusd              DOUBLE PRECISION,
                usdjpy              DOUBLE PRECISION,

                -- Volatility
                vix                 DOUBLE PRECISION,

                -- Derived
                yield_curve_2_10    DOUBLE PRECISION,
                yield_curve_3m_10   DOUBLE PRECISION
            );
        """))


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS macro CASCADE"))


def insert(df: pd.DataFrame):
    df.to_sql("macro", get_connection(), if_exists="append", index=False, method=_insert_ignore)


def get(start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    q = "SELECT * FROM macro WHERE TRUE"
    params = {}
    if start_date is not None:
        params["start"] = start_date
        q += " AND date >= :start"
    if end_date is not None:
        params["end"] = end_date
        q += " AND date <= :end"
    q += " ORDER BY date"
    return pd.read_sql_query(text(q), get_connection(), params=params)


def get_latest_date() -> str | None:
    with get_connection().connect() as conn:
        result = conn.execute(text("SELECT MAX(date) FROM macro")).scalar()
        return str(result) if result else None
