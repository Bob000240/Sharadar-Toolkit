from database.db_connection import get_connection
import numpy as np
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "ticker",
    "date",
    "close",
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "return_252d",
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_9",
    "ema_21",
    "ema_crossover_days_ago",
    "pct_from_sma_20",
    "pct_from_sma_50",
    "volume_sma_10",
    "volume_sma_50",
    "volume_ratio",
    "obv",
    "dollar_volume",
    "dollar_volume_20d_avg",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "atr_pct",
    "volatility_20",
    "vol_adjusted_momentum",
    "consolidation_tightness",
    "high_52w",
    "pct_from_52w_high",
    "r_squared_60d",
    "trend_slope_60d",
    "rolling_20d_high",
    "drawdown_from_recent_high",
]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_table():
    with get_connection().begin() as conn:
        conn.execute(
            text("""
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

                r_squared_60d           DOUBLE PRECISION,
                trend_slope_60d         DOUBLE PRECISION,

                rolling_20d_high        DOUBLE PRECISION,
                drawdown_from_recent_high DOUBLE PRECISION,

                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_indicators_ticker ON indicators (ticker);
        """)
        )


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS indicators CASCADE"))


def insert(df: pd.DataFrame):
    if df.empty:
        return
    df = df[_COLUMNS].replace([np.inf, -np.inf], np.nan)
    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    records = [{k: None if v is pd.NaT else v for k, v in r.items()} for r in records]
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO indicators ({_COL_LIST}) VALUES ({_BIND_LIST}) ON CONFLICT DO NOTHING"
            ),
            records,
        )


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


def get_latest(
    tickers: str | list[str] | None, signal_day: pd.Timestamp
) -> pd.DataFrame:
    params = {
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    ticker_clause = ""
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        ticker_clause = "AND ticker = ANY(:tickers)"
    q = text(f"""
        SELECT DISTINCT ON (ticker) *
        FROM indicators
        WHERE date <= :signal_day
          {ticker_clause}
        ORDER BY ticker, date DESC
    """)
    return pd.read_sql_query(q, get_connection(), params=params)
