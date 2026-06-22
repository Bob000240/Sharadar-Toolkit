"""
Institutional and insider data tables:
  insider_transactions   — SF2 (Form 4 filings)
  institutional_holdings — SF3 (holdings by ticker)
  institutional_summary  — SF3A (ownership summary by company)
  institutional_investors — SF3B (holdings by investor)
"""
from __future__ import annotations
from datetime import date
import pandas as pd
from sqlalchemy import text
from database.db_connection import get_connection

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL_INSIDER = """
CREATE TABLE IF NOT EXISTS insider_transactions (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              VARCHAR(16)  NOT NULL,
    filing_date         DATE         NOT NULL,
    transaction_date    DATE,
    owner_name          TEXT,
    owner_cik           VARCHAR(32),
    issuer_name         TEXT,
    issuer_cik          VARCHAR(32),
    is_director         BOOLEAN,
    is_officer          BOOLEAN,
    is_ten_pct_owner    BOOLEAN,
    transaction_code    VARCHAR(4),   -- P=purchase, S=sale, A=award, etc.
    transaction_shares  NUMERIC(20,4),
    transaction_price   NUMERIC(14,4),
    transaction_value   NUMERIC(20,4),
    shares_owned_after  NUMERIC(20,4),
    security_type       VARCHAR(64),
    security_title      VARCHAR(128),
    row_num             INT,
    updated_at          DATE,
    UNIQUE (ticker, filing_date, owner_cik, transaction_code, row_num)
);
CREATE INDEX IF NOT EXISTS idx_insider_ticker_date
    ON insider_transactions (ticker, filing_date DESC);
"""

DDL_SF3 = """
CREATE TABLE IF NOT EXISTS institutional_holdings (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              VARCHAR(16)  NOT NULL,
    calendar_date       DATE         NOT NULL,
    filing_date         DATE,
    investor_name       TEXT,
    security_type       VARCHAR(64),
    shares_held         NUMERIC(20,4),
    shares_changed      NUMERIC(20,4),
    shares_changed_pct  NUMERIC(10,4),
    market_value        NUMERIC(20,4),
    portfolio_pct       NUMERIC(10,4),
    updated_at          DATE,
    UNIQUE (ticker, calendar_date, investor_name)
);
CREATE INDEX IF NOT EXISTS idx_sf3_ticker_date
    ON institutional_holdings (ticker, calendar_date DESC);
"""

DDL_SF3A = """
CREATE TABLE IF NOT EXISTS institutional_summary (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              VARCHAR(16)  NOT NULL,
    calendar_date       DATE         NOT NULL,
    filing_date         DATE,
    -- Number of institutional holders
    shareholders        INT,
    shareholders_change INT,
    call_holders        INT,
    put_holders         INT,
    shares_held         NUMERIC(20,4),
    shares_held_change  NUMERIC(20,4),
    shares_held_pct     NUMERIC(10,4),  -- % of float held by institutions
    market_value        NUMERIC(20,4),
    updated_at          DATE,
    UNIQUE (ticker, calendar_date)
);
CREATE INDEX IF NOT EXISTS idx_sf3a_ticker_date
    ON institutional_summary (ticker, calendar_date DESC);
"""

DDL_SF3B = """
CREATE TABLE IF NOT EXISTS institutional_investors (
    id                  BIGSERIAL PRIMARY KEY,
    investor_name       TEXT         NOT NULL,
    calendar_date       DATE         NOT NULL,
    filing_date         DATE,
    ticker              VARCHAR(16),
    security_type       VARCHAR(64),
    shares_held         NUMERIC(20,4),
    shares_changed      NUMERIC(20,4),
    market_value        NUMERIC(20,4),
    portfolio_pct       NUMERIC(10,4),
    updated_at          DATE,
    UNIQUE (investor_name, calendar_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_sf3b_investor
    ON institutional_investors (investor_name, calendar_date DESC);
CREATE INDEX IF NOT EXISTS idx_sf3b_ticker
    ON institutional_investors (ticker, calendar_date DESC);
"""


def create_tables() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL_INSIDER))
        conn.execute(text(DDL_SF3))
        conn.execute(text(DDL_SF3A))
        conn.execute(text(DDL_SF3B))
        conn.commit()


def drop_tables() -> None:
    with get_connection().connect() as conn:
        for tbl in ("institutional_investors", "institutional_summary",
                    "institutional_holdings", "insider_transactions"):
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))
        conn.commit()


# ---------------------------------------------------------------------------
# Insider transactions (SF2)
# ---------------------------------------------------------------------------

_SF2_COLS = {
    "ticker": "ticker",
    "filingdate": "filing_date",
    "transactiondate": "transaction_date",
    "ownername": "owner_name",
    "ownercik": "owner_cik",
    "issuername": "issuer_name",
    "issuercik": "issuer_cik",
    "isdirector": "is_director",
    "isofficer": "is_officer",
    "istenpercentowner": "is_ten_pct_owner",
    "transactioncode": "transaction_code",
    "transactionshares": "transaction_shares",
    "transactionpricepershare": "transaction_price",
    "transactionvalue": "transaction_value",
    "sharesownedbeforetransaction": None,   # unused
    "sharesownedfollowingtransaction": "shares_owned_after",
    "securitytype": "security_type",
    "securitytitle": "security_title",
    "rownum": "row_num",
    "lastupdated": "updated_at",
}


def upsert_insider(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.rename(columns=_SF2_COLS).drop(
        columns=[c for c in df.columns if _SF2_COLS.get(c) is None], errors="ignore"
    )
    rows = df.where(pd.notnull(df), None).to_dict("records")
    sql = text("""
        INSERT INTO insider_transactions
            (ticker, filing_date, transaction_date, owner_name, owner_cik,
             issuer_name, issuer_cik, is_director, is_officer, is_ten_pct_owner,
             transaction_code, transaction_shares, transaction_price, transaction_value,
             shares_owned_after, security_type, security_title, row_num, updated_at)
        VALUES
            (:ticker, :filing_date, :transaction_date, :owner_name, :owner_cik,
             :issuer_name, :issuer_cik, :is_director, :is_officer, :is_ten_pct_owner,
             :transaction_code, :transaction_shares, :transaction_price, :transaction_value,
             :shares_owned_after, :security_type, :security_title, :row_num, :updated_at)
        ON CONFLICT (ticker, filing_date, owner_cik, transaction_code, row_num)
        DO NOTHING
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_insider(tickers: list[str], start_date: date, end_date: date) -> pd.DataFrame:
    sql = text("""
        SELECT * FROM insider_transactions
        WHERE ticker = ANY(:t) AND filing_date BETWEEN :s AND :e
        ORDER BY ticker, filing_date DESC
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(
            conn.execute(sql, {"t": tickers, "s": start_date, "e": end_date}).fetchall()
        )


# ---------------------------------------------------------------------------
# Institutional summary (SF3A) — most useful for signals
# ---------------------------------------------------------------------------

_SF3A_COLS = {
    "ticker": "ticker",
    "calendardate": "calendar_date",
    "filingdate": "filing_date",
    "shareholders": "shareholders",
    "shareholderschange": "shareholders_change",
    "callholders": "call_holders",
    "putholders": "put_holders",
    "sharesheld": "shares_held",
    "sharesheldchange": "shares_held_change",
    "sharesheldpercentofshares": "shares_held_pct",
    "marketvalue": "market_value",
    "lastupdated": "updated_at",
}


def upsert_institutional_summary(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.rename(columns=_SF3A_COLS)
    keep = [v for v in _SF3A_COLS.values() if v in df.columns]
    rows = df[keep].where(pd.notnull(df[keep]), None).to_dict("records")
    sql = text("""
        INSERT INTO institutional_summary
            (ticker, calendar_date, filing_date,
             shareholders, shareholders_change, call_holders, put_holders,
             shares_held, shares_held_change, shares_held_pct, market_value, updated_at)
        VALUES
            (:ticker, :calendar_date, :filing_date,
             :shareholders, :shareholders_change, :call_holders, :put_holders,
             :shares_held, :shares_held_change, :shares_held_pct, :market_value, :updated_at)
        ON CONFLICT (ticker, calendar_date) DO UPDATE SET
            shareholders        = EXCLUDED.shareholders,
            shareholders_change = EXCLUDED.shareholders_change,
            shares_held         = EXCLUDED.shares_held,
            shares_held_change  = EXCLUDED.shares_held_change,
            shares_held_pct     = EXCLUDED.shares_held_pct,
            market_value        = EXCLUDED.market_value,
            updated_at          = EXCLUDED.updated_at
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_institutional_summary(tickers: list[str], as_of: date) -> pd.DataFrame:
    """Most recent institutional summary row per ticker on or before as_of."""
    sql = text("""
        SELECT DISTINCT ON (ticker) *
        FROM institutional_summary
        WHERE ticker = ANY(:t) AND calendar_date <= :d
        ORDER BY ticker, calendar_date DESC
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(
            conn.execute(sql, {"t": tickers, "d": as_of}).fetchall()
        )


# ---------------------------------------------------------------------------
# SF3 and SF3B — bulk holders (lower priority, same pattern)
# ---------------------------------------------------------------------------

def upsert_institutional_holdings(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rename = {
        "ticker": "ticker", "calendardate": "calendar_date",
        "filingdate": "filing_date", "investorname": "investor_name",
        "securitytype": "security_type", "sharesheld": "shares_held",
        "sharesheldchange": "shares_changed",
        "sharesheldpercentchange": "shares_changed_pct",
        "marketvalue": "market_value", "portfoliopercent": "portfolio_pct",
        "lastupdated": "updated_at",
    }
    df = df.rename(columns=rename)
    keep = [v for v in rename.values() if v in df.columns]
    rows = df[keep].where(pd.notnull(df[keep]), None).to_dict("records")
    sql = text("""
        INSERT INTO institutional_holdings
            (ticker, calendar_date, filing_date, investor_name, security_type,
             shares_held, shares_changed, shares_changed_pct, market_value,
             portfolio_pct, updated_at)
        VALUES
            (:ticker, :calendar_date, :filing_date, :investor_name, :security_type,
             :shares_held, :shares_changed, :shares_changed_pct, :market_value,
             :portfolio_pct, :updated_at)
        ON CONFLICT (ticker, calendar_date, investor_name) DO NOTHING
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)
