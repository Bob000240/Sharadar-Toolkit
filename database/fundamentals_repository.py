from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Column definitions per table
# ---------------------------------------------------------------------------

_QUALITY_COLS = [
    "symbol", "date",
    "roe", "roa", "roic",
    "gross_margin", "operating_margin", "net_margin", "fcf_margin",
    "cash_conversion", "accruals_ratio",
    "debt_to_equity", "net_debt_to_ebitda", "interest_coverage",
    "current_ratio", "asset_turnover",
]

_VALUE_COLS = [
    "symbol", "date",
    "pe_ratio", "forward_pe", "earnings_yield",
    "pb_ratio", "p_tangible_book", "price_to_sales",
    "ev_ebitda", "ev_sales", "ev_fcf",
    "price_to_fcf", "fcf_yield",
    "dividend_yield", "buyback_yield", "shareholder_yield",
]

_GROWTH_COLS = [
    "symbol", "date", "period",
    "revenue_growth_yoy", "eps_growth_yoy",
    "revenue_growth_qoq", "eps_growth_qoq",
]

# Combined column list for get_latest_fundamentals JOIN result
# (excludes duplicate symbol/date/period columns)
_ALL_QUALITY = [c for c in _QUALITY_COLS if c not in ("symbol", "date")]
_ALL_VALUE = [c for c in _VALUE_COLS if c not in ("symbol", "date")]


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

def create_fundamentals_tables():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS quality_fundamentals (
                symbol              TEXT NOT NULL,
                date                DATE NOT NULL,
                roe                 DOUBLE PRECISION,
                roa                 DOUBLE PRECISION,
                roic                DOUBLE PRECISION,
                gross_margin        DOUBLE PRECISION,
                operating_margin    DOUBLE PRECISION,
                net_margin          DOUBLE PRECISION,
                fcf_margin          DOUBLE PRECISION,
                cash_conversion     DOUBLE PRECISION,
                accruals_ratio      DOUBLE PRECISION,
                debt_to_equity      DOUBLE PRECISION,
                net_debt_to_ebitda  DOUBLE PRECISION,
                interest_coverage   DOUBLE PRECISION,
                current_ratio       DOUBLE PRECISION,
                asset_turnover      DOUBLE PRECISION,
                PRIMARY KEY (symbol, date)
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS value_fundamentals (
                symbol              TEXT NOT NULL,
                date                DATE NOT NULL,
                pe_ratio            DOUBLE PRECISION,
                forward_pe          DOUBLE PRECISION,
                earnings_yield      DOUBLE PRECISION,
                pb_ratio            DOUBLE PRECISION,
                p_tangible_book     DOUBLE PRECISION,
                price_to_sales      DOUBLE PRECISION,
                ev_ebitda           DOUBLE PRECISION,
                ev_sales            DOUBLE PRECISION,
                ev_fcf              DOUBLE PRECISION,
                price_to_fcf        DOUBLE PRECISION,
                fcf_yield           DOUBLE PRECISION,
                dividend_yield      DOUBLE PRECISION,
                buyback_yield       DOUBLE PRECISION,
                shareholder_yield   DOUBLE PRECISION,
                PRIMARY KEY (symbol, date)
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS growth_fundamentals (
                symbol                  TEXT NOT NULL,
                date                    DATE NOT NULL,
                period                  TEXT NOT NULL,
                revenue_growth_yoy      DOUBLE PRECISION,
                eps_growth_yoy          DOUBLE PRECISION,
                revenue_growth_qoq      DOUBLE PRECISION,
                eps_growth_qoq          DOUBLE PRECISION,
                PRIMARY KEY (symbol, date, period)
            );
        """))


def drop_fundamentals_tables():
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS quality_fundamentals;"))
        conn.execute(text("DROP TABLE IF EXISTS value_fundamentals;"))
        conn.execute(text("DROP TABLE IF EXISTS growth_fundamentals;"))


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def _insert(table: str, cols: list[str], df: pd.DataFrame):
    missing = [c for c in cols if c not in df.columns]
    for c in missing:
        df[c] = None
    df = df[cols].where(pd.notnull(df[cols]), None)
    records = df.to_dict(orient="records")
    if not records:
        return
    col_list  = ", ".join(cols)
    bind_list = ", ".join(f":{c}" for c in cols)
    pk = {"quality_fundamentals": "(symbol, date)",
          "value_fundamentals":   "(symbol, date)",
          "growth_fundamentals":  "(symbol, date, period)"}[table]
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO {table} ({col_list})
            VALUES ({bind_list})
            ON CONFLICT {pk} DO NOTHING;
        """), records)


def delete_value_today(symbols: list[str], date) -> None:
    """Delete today's value rows so they can be refreshed with current prices."""
    engine = get_connection()
    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM value_fundamentals
            WHERE symbol = ANY(:symbols) AND date = :date
        """), {"symbols": symbols, "date": date})


def insert_quality(df: pd.DataFrame):
    _insert("quality_fundamentals", _QUALITY_COLS, df.copy())


def insert_value(df: pd.DataFrame):
    _insert("value_fundamentals", _VALUE_COLS, df.copy())


def insert_growth(df: pd.DataFrame):
    _insert("growth_fundamentals", _GROWTH_COLS, df.copy())


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_latest_fundamentals(symbols: str | list[str], signal_day: pd.Timestamp) -> pd.DataFrame:
    """
    Return one row per symbol joining the most recent quality, value, and growth data.
    Annual growth (yoy) and quarterly growth (qoq) are fetched from separate rows
    since they live on different dates in growth_fundamentals.
    """
    engine  = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    day     = signal_day.date() if hasattr(signal_day, "date") else signal_day

    _ANN_GROWTH = ["revenue_growth_yoy", "eps_growth_yoy"]
    _QTR_GROWTH = ["revenue_growth_qoq", "eps_growth_qoq"]

    q_cols  = ", ".join(f"q.{c}"  for c in _ALL_QUALITY)
    v_cols  = ", ".join(f"v.{c}"  for c in _ALL_VALUE)
    ga_cols = ", ".join(f"ga.{c}" for c in _ANN_GROWTH)
    gq_cols = ", ".join(f"gq.{c}" for c in _QTR_GROWTH)

    query = text(f"""
        SELECT
            COALESCE(q.symbol, v.symbol) AS symbol,
            {q_cols},
            {v_cols},
            {ga_cols},
            {gq_cols}
        FROM (
            SELECT DISTINCT ON (symbol) *
            FROM quality_fundamentals
            WHERE symbol = ANY(:symbols) AND date <= :day
            ORDER BY symbol, date DESC
        ) q
        FULL JOIN (
            SELECT DISTINCT ON (symbol) *
            FROM value_fundamentals
            WHERE symbol = ANY(:symbols) AND date <= :day
            ORDER BY symbol, date DESC
        ) v ON q.symbol = v.symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol) symbol, revenue_growth_yoy, eps_growth_yoy
            FROM growth_fundamentals
            WHERE symbol = ANY(:symbols) AND date <= :day AND period = 'annual'
            ORDER BY symbol, date DESC
        ) ga ON COALESCE(q.symbol, v.symbol) = ga.symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol) symbol, revenue_growth_qoq, eps_growth_qoq
            FROM growth_fundamentals
            WHERE symbol = ANY(:symbols) AND date <= :day AND period = 'quarter'
            ORDER BY symbol, date DESC
        ) gq ON COALESCE(q.symbol, v.symbol) = gq.symbol
    """)

    return pd.read_sql_query(query, engine, params={"symbols": symbols, "day": day})


def get_quality(
    symbols: str | list[str],
    start_date: str | None = None,
    end_date:   str | None = None,
) -> pd.DataFrame:
    return _range_query("quality_fundamentals", _QUALITY_COLS, symbols, start_date, end_date)


def get_value(
    symbols: str | list[str],
    start_date: str | None = None,
    end_date:   str | None = None,
) -> pd.DataFrame:
    return _range_query("value_fundamentals", _VALUE_COLS, symbols, start_date, end_date)


def get_growth(
    symbols: str | list[str],
    start_date: str | None = None,
    end_date:   str | None = None,
) -> pd.DataFrame:
    return _range_query("growth_fundamentals", _GROWTH_COLS, symbols, start_date, end_date)


def _range_query(table, cols, symbols, start_date, end_date) -> pd.DataFrame:
    engine  = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    col_list = ", ".join(cols)
    sql = f"SELECT {col_list} FROM {table} WHERE symbol = ANY(:symbols)"
    params: dict = {"symbols": symbols}
    if start_date is not None:
        sql += " AND date >= :start_date"
        params["start_date"] = start_date
    if end_date is not None:
        sql += " AND date <= :end_date"
        params["end_date"] = end_date
    sql += " ORDER BY symbol ASC, date ASC"
    df = pd.read_sql_query(text(sql), engine, params=params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df
