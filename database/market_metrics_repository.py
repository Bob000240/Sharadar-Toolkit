"""
Market-oriented Sharadar tables:
  daily_metrics      — DAILY (EV, market cap, PE, PB, PS, EV/EBITDA per ticker per day)
  market_metrics     — METRICS (beta, returns, 52w high/low, MAs, volume)
  corporate_events   — EVENTS (earnings dates and other event codes)
  corporate_actions  — ACTIONS (splits, dividends, spin-offs)
  sp500_membership   — SP500 (constituent history: additions and removals)
  fund_prices        — SFP (ETF/fund daily OHLCV)
"""
from __future__ import annotations
from datetime import date
import pandas as pd
from sqlalchemy import text
from database.db_connection import get_connection

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL_DAILY = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(16)  NOT NULL,
    date            DATE         NOT NULL,
    -- Valuation
    ev              NUMERIC(20,4),
    evebit          NUMERIC(14,4),
    evebitda        NUMERIC(14,4),
    marketcap       NUMERIC(20,4),
    pb              NUMERIC(14,4),
    pe              NUMERIC(14,4),
    ps              NUMERIC(14,4),
    lastupdated     DATE,
    UNIQUE (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_ticker_date ON daily_metrics (ticker, date DESC);
"""

DDL_METRICS = """
CREATE TABLE IF NOT EXISTS market_metrics (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(16)  NOT NULL,
    date            DATE         NOT NULL,
    -- Technical / risk
    beta            NUMERIC(10,4),
    high_52w        NUMERIC(14,4),
    low_52w         NUMERIC(14,4),
    ma_50           NUMERIC(14,4),
    ma_200          NUMERIC(14,4),
    -- Returns
    return_1m       NUMERIC(10,6),
    return_3m       NUMERIC(10,6),
    return_6m       NUMERIC(10,6),
    return_1y       NUMERIC(10,6),
    return_3y       NUMERIC(10,6),
    return_5y       NUMERIC(10,6),
    -- Volume
    volume_avg_30d  NUMERIC(20,4),
    volume_avg_90d  NUMERIC(20,4),
    lastupdated     DATE,
    UNIQUE (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_metrics_ticker_date ON market_metrics (ticker, date DESC);
"""

DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS corporate_events (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(16)  NOT NULL,
    date            DATE         NOT NULL,
    event_codes     TEXT,           -- comma-separated event codes (e.g. "EA,SD")
    UNIQUE (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_events_ticker_date ON corporate_events (ticker, date DESC);
"""

DDL_ACTIONS = """
CREATE TABLE IF NOT EXISTS corporate_actions (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(16)  NOT NULL,
    date            DATE         NOT NULL,
    action          VARCHAR(32),    -- split, dividend, spinoff, merger, etc.
    name            TEXT,
    value           NUMERIC(20,8),  -- split ratio, dividend amount, etc.
    contra_ticker   VARCHAR(16),    -- for spinoffs / mergers
    updated_at      DATE,
    UNIQUE (ticker, date, action)
);
CREATE INDEX IF NOT EXISTS idx_actions_ticker_date ON corporate_actions (ticker, date DESC);
"""

DDL_SP500 = """
CREATE TABLE IF NOT EXISTS sp500_membership (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(16)  NOT NULL,
    date            DATE         NOT NULL,
    action          VARCHAR(8),     -- added / removed
    name            TEXT,
    UNIQUE (ticker, date, action)
);
CREATE INDEX IF NOT EXISTS idx_sp500_date ON sp500_membership (date DESC);
"""

DDL_FUND_PRICES = """
CREATE TABLE IF NOT EXISTS fund_prices (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(16)  NOT NULL,
    date            DATE         NOT NULL,
    open            NUMERIC(14,4),
    high            NUMERIC(14,4),
    low             NUMERIC(14,4),
    close           NUMERIC(14,4),
    volume          BIGINT,
    closeadj        NUMERIC(14,4),
    lastupdated     DATE,
    UNIQUE (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_fund_prices_ticker_date ON fund_prices (ticker, date DESC);
"""


def create_tables() -> None:
    with get_connection().connect() as conn:
        for ddl in (DDL_DAILY, DDL_METRICS, DDL_EVENTS, DDL_ACTIONS, DDL_SP500, DDL_FUND_PRICES):
            conn.execute(text(ddl))
        conn.commit()


def drop_tables() -> None:
    with get_connection().connect() as conn:
        for tbl in ("fund_prices", "sp500_membership", "corporate_actions",
                    "corporate_events", "market_metrics", "daily_metrics"):
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))
        conn.commit()


# ---------------------------------------------------------------------------
# DAILY — per-ticker valuation metrics
# ---------------------------------------------------------------------------

_DAILY_COLS = {
    "ticker": "ticker", "date": "date",
    "ev": "ev", "evebit": "evebit", "evebitda": "evebitda",
    "marketcap": "marketcap", "pb": "pb", "pe": "pe", "ps": "ps",
    "lastupdated": "lastupdated",
}


def upsert_daily(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.rename(columns=_DAILY_COLS)
    keep = [v for v in _DAILY_COLS.values() if v in df.columns]
    rows = df[keep].where(pd.notnull(df[keep]), None).to_dict("records")
    sql = text("""
        INSERT INTO daily_metrics (ticker, date, ev, evebit, evebitda, marketcap, pb, pe, ps, lastupdated)
        VALUES (:ticker, :date, :ev, :evebit, :evebitda, :marketcap, :pb, :pe, :ps, :lastupdated)
        ON CONFLICT (ticker, date) DO UPDATE SET
            ev=EXCLUDED.ev, evebit=EXCLUDED.evebit, evebitda=EXCLUDED.evebitda,
            marketcap=EXCLUDED.marketcap, pb=EXCLUDED.pb, pe=EXCLUDED.pe, ps=EXCLUDED.ps,
            lastupdated=EXCLUDED.lastupdated
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_daily(tickers: list[str], as_of: date) -> pd.DataFrame:
    """Most recent row per ticker on or before as_of."""
    sql = text("""
        SELECT DISTINCT ON (ticker) *
        FROM daily_metrics WHERE ticker = ANY(:t) AND date <= :d
        ORDER BY ticker, date DESC
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(conn.execute(sql, {"t": tickers, "d": as_of}).fetchall())


def get_daily_series(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    sql = text("""
        SELECT * FROM daily_metrics
        WHERE ticker = ANY(:t) AND date BETWEEN :s AND :e
        ORDER BY ticker, date
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(conn.execute(sql, {"t": tickers, "s": start, "e": end}).fetchall())


# ---------------------------------------------------------------------------
# METRICS — technical / risk metrics
# ---------------------------------------------------------------------------

_METRICS_MAP = {
    "ticker": "ticker", "date": "date",
    "beta": "beta",
    "high52w": "high_52w", "low52w": "low_52w",
    "ma50": "ma_50", "ma200": "ma_200",
    "return1m": "return_1m", "return3m": "return_3m",
    "return6m": "return_6m", "return1y": "return_1y",
    "return3y": "return_3y", "return5y": "return_5y",
    "volumeavg30d": "volume_avg_30d", "volumeavg90d": "volume_avg_90d",
    "lastupdated": "lastupdated",
}


def upsert_market_metrics(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.rename(columns=_METRICS_MAP)
    keep = [v for v in _METRICS_MAP.values() if v in df.columns]
    rows = df[keep].where(pd.notnull(df[keep]), None).to_dict("records")
    sql = text("""
        INSERT INTO market_metrics
            (ticker, date, beta, high_52w, low_52w, ma_50, ma_200,
             return_1m, return_3m, return_6m, return_1y, return_3y, return_5y,
             volume_avg_30d, volume_avg_90d, lastupdated)
        VALUES
            (:ticker, :date, :beta, :high_52w, :low_52w, :ma_50, :ma_200,
             :return_1m, :return_3m, :return_6m, :return_1y, :return_3y, :return_5y,
             :volume_avg_30d, :volume_avg_90d, :lastupdated)
        ON CONFLICT (ticker, date) DO UPDATE SET
            beta=EXCLUDED.beta, high_52w=EXCLUDED.high_52w, low_52w=EXCLUDED.low_52w,
            ma_50=EXCLUDED.ma_50, ma_200=EXCLUDED.ma_200,
            return_1m=EXCLUDED.return_1m, return_3m=EXCLUDED.return_3m,
            return_6m=EXCLUDED.return_6m, return_1y=EXCLUDED.return_1y,
            return_3y=EXCLUDED.return_3y, return_5y=EXCLUDED.return_5y,
            volume_avg_30d=EXCLUDED.volume_avg_30d, volume_avg_90d=EXCLUDED.volume_avg_90d,
            lastupdated=EXCLUDED.lastupdated
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_market_metrics(tickers: list[str], as_of: date) -> pd.DataFrame:
    sql = text("""
        SELECT DISTINCT ON (ticker) *
        FROM market_metrics WHERE ticker = ANY(:t) AND date <= :d
        ORDER BY ticker, date DESC
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(conn.execute(sql, {"t": tickers, "d": as_of}).fetchall())


# ---------------------------------------------------------------------------
# EVENTS — earnings and corporate events
# ---------------------------------------------------------------------------

def upsert_events(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.rename(columns={"eventcodes": "event_codes"})
    rows = df[["ticker", "date", "event_codes"]].where(
        pd.notnull(df[["ticker", "date", "event_codes"]]), None
    ).to_dict("records")
    sql = text("""
        INSERT INTO corporate_events (ticker, date, event_codes)
        VALUES (:ticker, :date, :event_codes)
        ON CONFLICT (ticker, date) DO UPDATE SET event_codes = EXCLUDED.event_codes
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_events(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    sql = text("""
        SELECT * FROM corporate_events
        WHERE ticker = ANY(:t) AND date BETWEEN :s AND :e
        ORDER BY ticker, date
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(conn.execute(sql, {"t": tickers, "s": start, "e": end}).fetchall())


# ---------------------------------------------------------------------------
# ACTIONS — splits, dividends, spin-offs
# ---------------------------------------------------------------------------

def upsert_actions(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rename = {"name": "name", "ticker": "ticker", "date": "date",
               "action": "action", "value": "value", "contraticker": "contra_ticker",
               "lastupdated": "updated_at"}
    df = df.rename(columns=rename)
    keep = [c for c in rename.values() if c in df.columns]
    rows = df[keep].where(pd.notnull(df[keep]), None).to_dict("records")
    sql = text("""
        INSERT INTO corporate_actions (ticker, date, action, name, value, contra_ticker, updated_at)
        VALUES (:ticker, :date, :action, :name, :value, :contra_ticker, :updated_at)
        ON CONFLICT (ticker, date, action) DO NOTHING
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# SP500 — constituent history
# ---------------------------------------------------------------------------

def upsert_sp500(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.rename(columns={"action": "action", "name": "name",
                              "ticker": "ticker", "date": "date"})
    rows = df[["ticker", "date", "action", "name"]].where(
        pd.notnull(df[["ticker", "date", "action", "name"]]), None
    ).to_dict("records")
    sql = text("""
        INSERT INTO sp500_membership (ticker, date, action, name)
        VALUES (:ticker, :date, :action, :name)
        ON CONFLICT (ticker, date, action) DO NOTHING
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_sp500_constituents(as_of: date) -> list[str]:
    """Return tickers that were members of the S&P 500 as of as_of."""
    sql = text("""
        SELECT DISTINCT ticker FROM (
            SELECT ticker, MAX(date) AS last_action_date,
                   (array_agg(action ORDER BY date DESC))[1] AS last_action
            FROM sp500_membership
            WHERE date <= :d
            GROUP BY ticker
        ) sub
        WHERE last_action = 'added'
    """)
    with get_connection().connect() as conn:
        return [r[0] for r in conn.execute(sql, {"d": as_of})]


# ---------------------------------------------------------------------------
# FUND PRICES (SFP)
# ---------------------------------------------------------------------------

def upsert_fund_prices(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rename = {
        "ticker": "ticker", "date": "date",
        "open": "open", "high": "high", "low": "low",
        "close": "close", "volume": "volume",
        "closeadj": "closeadj", "lastupdated": "lastupdated",
    }
    df = df.rename(columns=rename)
    keep = [v for v in rename.values() if v in df.columns]
    rows = df[keep].where(pd.notnull(df[keep]), None).to_dict("records")
    sql = text("""
        INSERT INTO fund_prices (ticker, date, open, high, low, close, volume, closeadj, lastupdated)
        VALUES (:ticker, :date, :open, :high, :low, :close, :volume, :closeadj, :lastupdated)
        ON CONFLICT (ticker, date) DO UPDATE SET
            open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
            close=EXCLUDED.close, volume=EXCLUDED.volume,
            closeadj=EXCLUDED.closeadj, lastupdated=EXCLUDED.lastupdated
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, rows)
        conn.commit()
    return len(rows)


def get_fund_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    sql = text("""
        SELECT * FROM fund_prices
        WHERE ticker = ANY(:t) AND date BETWEEN :s AND :e
        ORDER BY ticker, date
    """)
    with get_connection().connect() as conn:
        return pd.DataFrame(conn.execute(sql, {"t": tickers, "s": start, "e": end}).fetchall())
