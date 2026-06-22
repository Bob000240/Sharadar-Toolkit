"""
Single unified fundamentals table sourced from Sharadar SF1.
Point-in-time safe: all queries filter on date_key (filing date), not calendar_date.

Replaces the old quality_fundamentals / value_fundamentals / growth_fundamentals trio.
"""
from __future__ import annotations
import pandas as pd
from sqlalchemy import text
from database.db_connection import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker              VARCHAR(16)  NOT NULL,
    dimension           VARCHAR(8)   NOT NULL,   -- ARY, ARQ, ART, MRY, MRQ, MRT
    calendar_date       DATE         NOT NULL,   -- period end (not safe for point-in-time)
    date_key            DATE         NOT NULL,   -- filing date (point-in-time safe key)
    report_period       DATE,
    fiscal_period       VARCHAR(8),
    fiscal_year         INT,
    last_updated        DATE,

    -- Income statement
    revenue             NUMERIC(20,4),
    gross_profit        NUMERIC(20,4),
    operating_income    NUMERIC(20,4),
    net_income          NUMERIC(20,4),
    ebit                NUMERIC(20,4),
    ebitda              NUMERIC(20,4),
    eps                 NUMERIC(14,6),
    eps_diluted         NUMERIC(14,6),
    interest_expense    NUMERIC(20,4),

    -- Balance sheet
    assets              NUMERIC(20,4),
    assets_current      NUMERIC(20,4),
    equity              NUMERIC(20,4),
    liabilities         NUMERIC(20,4),
    debt                NUMERIC(20,4),
    debt_current        NUMERIC(20,4),
    cash                NUMERIC(20,4),
    inventory           NUMERIC(20,4),
    receivables         NUMERIC(20,4),
    payables            NUMERIC(20,4),

    -- Cash flow
    ncfo                NUMERIC(20,4),   -- operating cash flow
    fcf                 NUMERIC(20,4),
    capex               NUMERIC(20,4),

    -- Pre-computed ratios from SF1
    roe                 NUMERIC(14,6),
    roa                 NUMERIC(14,6),
    roic                NUMERIC(14,6),
    gross_margin        NUMERIC(10,6),
    ebitda_margin       NUMERIC(10,6),
    net_margin          NUMERIC(10,6),
    fcf_margin          NUMERIC(10,6),
    current_ratio       NUMERIC(10,4),
    debt_to_equity      NUMERIC(10,4),
    asset_turnover      NUMERIC(10,4),
    interest_coverage   NUMERIC(10,4),
    piotroski           INT,            -- 0-9 Piotroski F-score

    -- Shares outstanding
    shares_basic        NUMERIC(20,4),
    shares_diluted      NUMERIC(20,4),
    shares_wabdil       NUMERIC(20,4),

    -- Revenue (USD-normalized for cross-currency comparison)
    revenue_usd         NUMERIC(20,4),
    equity_usd          NUMERIC(20,4),
    eps_usd             NUMERIC(14,6),

    PRIMARY KEY (ticker, dimension, date_key)
);
CREATE INDEX IF NOT EXISTS idx_fund_ticker_dim_cal
    ON fundamentals (ticker, dimension, calendar_date DESC);
CREATE INDEX IF NOT EXISTS idx_fund_ticker_datekey
    ON fundamentals (ticker, date_key DESC);
"""

# Mapping from SF1 raw column names → our DB column names
_SF1_MAP = {
    "ticker":           "ticker",
    "dimension":        "dimension",
    "calendardate":     "calendar_date",
    "datekey":          "date_key",
    "reportperiod":     "report_period",
    "fiscalperiod":     "fiscal_period",
    "fiscalyear":       "fiscal_year",
    "lastupdated":      "last_updated",
    "revenue":          "revenue",
    "gp":               "gross_profit",
    "opinc":            "operating_income",
    "netinc":           "net_income",
    "ebit":             "ebit",
    "ebitda":           "ebitda",
    "eps":              "eps",
    "epsdil":           "eps_diluted",
    "intexp":           "interest_expense",
    "assets":           "assets",
    "assetsc":          "assets_current",
    "equity":           "equity",
    "liabilities":      "liabilities",
    "debt":             "debt",
    "debtc":            "debt_current",
    "cashneq":          "cash",
    "inventory":        "inventory",
    "receivables":      "receivables",
    "payables":         "payables",
    "ncfo":             "ncfo",
    "fcf":              "fcf",
    "capex":            "capex",
    "roe":              "roe",
    "roa":              "roa",
    "roic":             "roic",
    "grossmargin":      "gross_margin",
    "ebitdamargin":     "ebitda_margin",
    "netmargin":        "net_margin",
    "fcfmargin":        "fcf_margin",
    "currentratio":     "current_ratio",
    "de":               "debt_to_equity",
    "assetturnover":    "asset_turnover",
    "intcov":           "interest_coverage",
    "piotroski":        "piotroski",
    "sharesbasic":      "shares_basic",
    "sharesdiluted":    "shares_diluted",
    "shareswabdil":     "shares_wabdil",
    "revenueusd":       "revenue_usd",
    "equityusd":        "equity_usd",
    "epsusd":           "eps_usd",
}

_DB_COLS = list({v for v in _SF1_MAP.values()})


def create_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL))
        conn.commit()


def drop_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fundamentals CASCADE"))
        conn.commit()


def _df_from_sf1(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=_SF1_MAP)
    keep = [c for c in _DB_COLS if c in df.columns]
    return df[keep].where(pd.notnull(df[keep]), None)


def upsert_fundamentals(df: pd.DataFrame) -> int:
    """Map SF1 dataframe columns and upsert into fundamentals table."""
    df = _df_from_sf1(df)
    if df.empty:
        return 0

    cols = [c for c in _DB_COLS if c in df.columns]
    col_list  = ", ".join(cols)
    bind_list = ", ".join(f":{c}" for c in cols)
    non_pk = [c for c in cols if c not in ("ticker", "dimension", "date_key")]
    update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in non_pk)

    sql = text(f"""
        INSERT INTO fundamentals ({col_list})
        VALUES ({bind_list})
        ON CONFLICT (ticker, dimension, date_key) DO UPDATE SET {update_set}
    """)
    rows = df[cols].to_dict("records")
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_fundamentals(
    tickers: list[str],
    dimension: str,
    as_of: date | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Most recent row per ticker on or before as_of (point-in-time safe via date_key)."""
    day = as_of.date() if hasattr(as_of, "date") else as_of
    if day is None:
        sql = text("""
            SELECT DISTINCT ON (ticker) * FROM fundamentals
            WHERE ticker = ANY(:t) AND dimension = :dim
            ORDER BY ticker, date_key DESC
        """)
        params = {"t": tickers, "dim": dimension}
    else:
        sql = text("""
            SELECT DISTINCT ON (ticker) * FROM fundamentals
            WHERE ticker = ANY(:t) AND dimension = :dim AND date_key <= :d
            ORDER BY ticker, date_key DESC
        """)
        params = {"t": tickers, "dim": dimension, "d": day}
    with get_connection().connect() as conn:
        return pd.DataFrame(conn.execute(sql, params).fetchall())


def get_fundamentals_series(
    tickers: list[str],
    dimension: str,
    start: date | str | None = None,
    end: date | str | None = None,
) -> pd.DataFrame:
    sql = text("""
        SELECT * FROM fundamentals
        WHERE ticker = ANY(:t) AND dimension = :dim
          AND (:s IS NULL OR date_key >= :s)
          AND (:e IS NULL OR date_key <= :e)
        ORDER BY ticker, date_key
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(
            conn.execute(sql, {"t": tickers, "dim": dimension, "s": start, "e": end}).fetchall()
        )


# ---------------------------------------------------------------------------
# Backward-compat shims for existing code that calls the old three-table API
# ---------------------------------------------------------------------------

def get_latest_fundamentals(symbols: str | list[str], signal_day: pd.Timestamp) -> pd.DataFrame:
    """Single-row-per-ticker join used by legacy signal modules.

    Returns ARY (annual) row.  Callers expecting the old quality/value/growth
    column set should migrate to get_fundamentals() directly.
    """
    tickers = [symbols] if isinstance(symbols, str) else symbols
    df = get_fundamentals(tickers, dimension="ARY", as_of=signal_day)
    if not df.empty and "ticker" in df.columns:
        df = df.rename(columns={"ticker": "symbol"})
    return df


# Keep old drop/create names so setup_db.py can call them without importing old code.
def drop_fundamentals_tables() -> None:
    drop_table()


def create_fundamentals_tables() -> None:
    create_table()
