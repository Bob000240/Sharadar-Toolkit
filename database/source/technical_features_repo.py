"""Persistence for daily OHLCV-derived technical features."""

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
    "pct_from_sma_200",
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
_NON_PK = [c for c in _COLUMNS if c not in ("ticker", "date")]
_UPDATE_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in _NON_PK)


def create_table():
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            DO $$
            BEGIN
                IF to_regclass('technical_features') IS NOT NULL
                   AND to_regclass('indicators') IS NOT NULL THEN
                    RAISE EXCEPTION
                        'Both technical_features and legacy indicators tables exist';
                ELSIF to_regclass('technical_features') IS NULL
                      AND to_regclass('indicators') IS NOT NULL THEN
                    ALTER TABLE indicators RENAME TO technical_features;
                END IF;

                IF to_regclass('technical_features') IS NOT NULL
                   AND EXISTS (
                       SELECT 1
                       FROM pg_constraint
                       WHERE conrelid = 'technical_features'::regclass
                         AND conname = 'indicators_pkey'
                   ) THEN
                    ALTER TABLE technical_features
                        RENAME CONSTRAINT indicators_pkey
                        TO technical_features_pkey;
                END IF;
            END
            $$;

            CREATE TABLE IF NOT EXISTS technical_features (
                ticker TEXT NOT NULL,
                date DATE NOT NULL,
                close DOUBLE PRECISION,
                return_1d DOUBLE PRECISION,
                return_5d DOUBLE PRECISION,
                return_20d DOUBLE PRECISION,
                return_60d DOUBLE PRECISION,
                return_252d DOUBLE PRECISION,
                sma_20 DOUBLE PRECISION,
                sma_50 DOUBLE PRECISION,
                sma_200 DOUBLE PRECISION,
                ema_9 DOUBLE PRECISION,
                ema_21 DOUBLE PRECISION,
                ema_crossover_days_ago DOUBLE PRECISION,
                pct_from_sma_20 DOUBLE PRECISION,
                pct_from_sma_50 DOUBLE PRECISION,
                pct_from_sma_200 DOUBLE PRECISION,
                volume_sma_10 DOUBLE PRECISION,
                volume_sma_50 DOUBLE PRECISION,
                volume_ratio DOUBLE PRECISION,
                obv DOUBLE PRECISION,
                dollar_volume DOUBLE PRECISION,
                dollar_volume_20d_avg DOUBLE PRECISION,
                rsi_14 DOUBLE PRECISION,
                macd DOUBLE PRECISION,
                macd_signal DOUBLE PRECISION,
                macd_hist DOUBLE PRECISION,
                atr_14 DOUBLE PRECISION,
                atr_pct DOUBLE PRECISION,
                volatility_20 DOUBLE PRECISION,
                vol_adjusted_momentum DOUBLE PRECISION,
                consolidation_tightness DOUBLE PRECISION,
                high_52w DOUBLE PRECISION,
                pct_from_52w_high DOUBLE PRECISION,
                r_squared_60d DOUBLE PRECISION,
                trend_slope_60d DOUBLE PRECISION,
                rolling_20d_high DOUBLE PRECISION,
                drawdown_from_recent_high DOUBLE PRECISION,
                PRIMARY KEY (ticker, date)
            );
        """)
        )


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS technical_features CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS indicators CASCADE"))


def insert(df: pd.DataFrame):
    if df.empty:
        return
    frame = df[_COLUMNS].replace([np.inf, -np.inf], np.nan).astype(object)
    records = frame.where(frame.notna(), None).to_dict(orient="records")
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO technical_features ({_COL_LIST}) VALUES ({_BIND_LIST}) "
                f"ON CONFLICT (ticker, date) DO UPDATE SET {_UPDATE_SET}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    q = "SELECT * FROM technical_features WHERE TRUE"
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


def is_empty() -> bool:
    """Whether any features have been computed yet. EXISTS short-circuits on the
    first row, unlike a per-ticker GROUP BY over the whole table."""
    with get_connection().connect() as conn:
        return conn.execute(
            text("SELECT NOT EXISTS (SELECT 1 FROM technical_features)")
        ).scalar()


def get_missing_feature_dates() -> pd.DataFrame:
    """Return equity-price keys without a matching technical-feature row."""
    q = text("""
        SELECT ep.ticker, ep.date
        FROM equity_prices ep
        LEFT JOIN technical_features tf
          ON tf.ticker = ep.ticker
         AND tf.date = ep.date
        WHERE tf.ticker IS NULL
        ORDER BY ep.ticker, ep.date
    """)
    return pd.read_sql_query(q, get_connection())


def get_stale_feature_tickers() -> list[str]:
    q = text("""
        SELECT DISTINCT ep.ticker
        FROM equity_prices ep
        JOIN technical_features tf
          ON tf.ticker = ep.ticker
         AND tf.date = ep.date
        WHERE ep.close IS DISTINCT FROM tf.close
        ORDER BY ep.ticker
    """)
    return pd.read_sql_query(q, get_connection())["ticker"].tolist()


def get_latest_rows(
    tickers: str | list[str] | None, signal_day: pd.Timestamp
) -> pd.DataFrame:
    """Each ticker's most recent feature row on or before `signal_day`.

    With an explicit ticker list this drives one index seek per ticker against
    the (ticker, date) primary key. `DISTINCT ON` over the same set instead
    reads every historical row for every ticker before discarding all but the
    newest — roughly 14M rows to return 5k, and ~15x slower. There is no lower
    date bound in either form, so a long-delisted ticker still resolves to its
    final row.
    """
    signal_day = signal_day.date() if hasattr(signal_day, "date") else signal_day

    if tickers is None:
        return pd.read_sql_query(
            text("""
                SELECT DISTINCT ON (ticker) *
                FROM technical_features
                WHERE date <= :signal_day
                ORDER BY ticker, date DESC
            """),
            get_connection(),
            params={"signal_day": signal_day},
        )

    return pd.read_sql_query(
        text("""
            SELECT latest.*
            FROM unnest(CAST(:tickers AS text[])) AS wanted(ticker)
            JOIN LATERAL (
                SELECT *
                FROM technical_features AS tf
                WHERE tf.ticker = wanted.ticker
                  AND tf.date <= :signal_day
                ORDER BY tf.date DESC
                LIMIT 1
            ) AS latest ON TRUE
            ORDER BY latest.ticker
        """),
        get_connection(),
        params={
            "tickers": [tickers] if isinstance(tickers, str) else list(tickers),
            "signal_day": signal_day,
        },
    )
