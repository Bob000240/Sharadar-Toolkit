from database.db_connection import get_connection
from database.market.db_utils import _insert_ignore
import numpy as np
import pandas as pd
from sqlalchemy import text

INDICATOR_COLUMNS = [
    "ticker", "date", "close",
    "return_1d", "return_5d", "return_20d", "return_60d", "return_252d",
    "sma_20", "sma_50", "sma_200",
    "ema_9", "ema_21", "ema_9_above_21", "ema_crossover_days_ago",
    "pct_from_sma_20", "pct_from_sma_50",
    "volume_sma_10", "volume_sma_50", "volume_ratio",
    "obv", "dollar_volume", "dollar_volume_20d_avg",
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "atr_14", "atr_pct", "volatility_20", "vol_adjusted_momentum", "consolidation_tightness",
    "high_52w", "pct_from_52w_high", "new_52w_high",
    "r_squared_60d", "trend_slope_60d", "slope_x_r2",
    "rolling_20d_high", "drawdown_from_recent_high", "price_vs_20d_high",
    "momentum_accel_20_60", "momentum_accel_5_20",
]


def create_table():
    with get_connection().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS indicators (
                ticker                  TEXT            NOT NULL,
                date                    DATE            NOT NULL,
                close                   DOUBLE PRECISION,

                return_1d               DOUBLE PRECISION,
                return_5d               DOUBLE PRECISION,
                return_20d              DOUBLE PRECISION,
                return_60d              DOUBLE PRECISION,
                return_252d             DOUBLE PRECISION,

                sma_20                  DOUBLE PRECISION,
                sma_50                  DOUBLE PRECISION,
                sma_200                 DOUBLE PRECISION,
                ema_9                   DOUBLE PRECISION,
                ema_21                  DOUBLE PRECISION,
                ema_9_above_21          BOOLEAN,
                ema_crossover_days_ago  DOUBLE PRECISION,
                pct_from_sma_20         DOUBLE PRECISION,
                pct_from_sma_50         DOUBLE PRECISION,

                volume_sma_10           DOUBLE PRECISION,
                volume_sma_50           DOUBLE PRECISION,
                volume_ratio            DOUBLE PRECISION,
                obv                     DOUBLE PRECISION,
                dollar_volume           DOUBLE PRECISION,
                dollar_volume_20d_avg   DOUBLE PRECISION,

                rsi_14                  DOUBLE PRECISION,
                macd                    DOUBLE PRECISION,
                macd_signal             DOUBLE PRECISION,
                macd_hist               DOUBLE PRECISION,

                atr_14                  DOUBLE PRECISION,
                atr_pct                 DOUBLE PRECISION,
                volatility_20           DOUBLE PRECISION,
                vol_adjusted_momentum   DOUBLE PRECISION,
                consolidation_tightness DOUBLE PRECISION,

                high_52w                DOUBLE PRECISION,
                pct_from_52w_high       DOUBLE PRECISION,
                new_52w_high            BOOLEAN,

                r_squared_60d           DOUBLE PRECISION,
                trend_slope_60d         DOUBLE PRECISION,
                slope_x_r2              DOUBLE PRECISION,

                rolling_20d_high        DOUBLE PRECISION,
                drawdown_from_recent_high DOUBLE PRECISION,
                price_vs_20d_high       DOUBLE PRECISION,

                momentum_accel_20_60    DOUBLE PRECISION,
                momentum_accel_5_20     DOUBLE PRECISION,

                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_indicators_ticker ON indicators (ticker);
        """))


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS indicators CASCADE"))


def insert(df: pd.DataFrame):
    if df.empty:
        return
    missing = sorted(set(INDICATOR_COLUMNS) - set(df.columns))
    if missing:
        raise ValueError(f"Missing indicator columns: {missing}")
    df = df[INDICATOR_COLUMNS].copy()
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.where(pd.notnull(df), None)
    df.to_sql("indicators", get_connection(), if_exists="append", index=False, method=_insert_ignore)


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    q = "SELECT * FROM indicators WHERE TRUE"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " AND ticker = ANY(:tickers)"
    if start_date is not None:
        params["start"] = start_date
        q += " AND date >= :start"
    if end_date is not None:
        params["end"] = end_date
        q += " AND date <= :end"
    q += " ORDER BY ticker, date"
    return pd.read_sql_query(text(q), get_connection(), params=params)


def get_latest_date(tickers: str | list[str] | None = None) -> pd.DataFrame:
    q = "SELECT ticker, MAX(date) AS latest_date FROM indicators"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " WHERE ticker = ANY(:tickers)"
    q += " GROUP BY ticker"
    return pd.read_sql_query(text(q), get_connection(), params=params)


def get_latest(tickers: str | list[str], signal_day: pd.Timestamp) -> pd.DataFrame:
    params = {
        "tickers": [tickers] if isinstance(tickers, str) else tickers,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    q = text("""
        SELECT DISTINCT ON (ticker) *
        FROM indicators
        WHERE ticker = ANY(:tickers)
          AND date <= :signal_day
        ORDER BY ticker, date DESC
    """)
    return pd.read_sql_query(q, get_connection(), params=params)
