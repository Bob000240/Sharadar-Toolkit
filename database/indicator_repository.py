from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text


def create_indicators_table():
    engine = get_connection()

    query = text("""
        CREATE TABLE IF NOT EXISTS indicators_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,

            -- Returns
            return_1d DOUBLE PRECISION,
            return_5d DOUBLE PRECISION,
            return_20d DOUBLE PRECISION,
            return_60d DOUBLE PRECISION,
            return_252d DOUBLE PRECISION,

            -- Moving averages
            sma_20 DOUBLE PRECISION,
            sma_50 DOUBLE PRECISION,
            sma_200 DOUBLE PRECISION,

            -- Volume
            volume_sma_10 DOUBLE PRECISION,
            volume_sma_50 DOUBLE PRECISION,
            volume_ratio DOUBLE PRECISION,
            obv DOUBLE PRECISION,
            dollar_volume DOUBLE PRECISION,
            dollar_volume_20d_avg DOUBLE PRECISION,

            -- Oscillators
            rsi_14 DOUBLE PRECISION,
            macd DOUBLE PRECISION,
            macd_signal DOUBLE PRECISION,
            macd_hist DOUBLE PRECISION,

            -- ATR / volatility
            atr_14 DOUBLE PRECISION,
            atr_pct DOUBLE PRECISION,
            volatility_20 DOUBLE PRECISION,
            vol_adjusted_momentum DOUBLE PRECISION,

            -- 52w high / trend structure
            high_52w DOUBLE PRECISION,
            pct_from_52w_high DOUBLE PRECISION,
            new_52w_high BOOLEAN,

            -- Trend quality
            r_squared_60d DOUBLE PRECISION,
            trend_slope_60d DOUBLE PRECISION,
            slope_x_r2 DOUBLE PRECISION,

            -- Drawdown
            rolling_20d_high DOUBLE PRECISION,
            drawdown_from_recent_high DOUBLE PRECISION,

            -- Acceleration
            momentum_accel_20_60 DOUBLE PRECISION,
            momentum_accel_5_20 DOUBLE PRECISION,

            -- Breakout signals
            price_vs_20d_high DOUBLE PRECISION,
            consolidation_tightness DOUBLE PRECISION,

            -- Pullback signals
            pct_from_sma_20 DOUBLE PRECISION,
            pct_from_sma_50 DOUBLE PRECISION,

            -- EMA crossover signals
            ema_9 DOUBLE PRECISION,
            ema_21 DOUBLE PRECISION,
            ema_9_above_21 BOOLEAN,
            ema_crossover_days_ago DOUBLE PRECISION,

            PRIMARY KEY (symbol, date)
        );
    """)

    with engine.begin() as conn:
        conn.execute(query)


def drop_indicators_table():
    engine = get_connection()

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS indicators_data;"))


_COLUMNS = [
    "symbol",
    "date",
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "return_252d",
    "sma_20",
    "sma_50",
    "sma_200",
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
    "high_52w",
    "pct_from_52w_high",
    "new_52w_high",
    "r_squared_60d",
    "trend_slope_60d",
    "slope_x_r2",
    "rolling_20d_high",
    "drawdown_from_recent_high",
    "momentum_accel_20_60",
    "momentum_accel_5_20",
    "price_vs_20d_high",
    "consolidation_tightness",
    "pct_from_sma_20",
    "pct_from_sma_50",
    "ema_9",
    "ema_21",
    "ema_9_above_21",
    "ema_crossover_days_ago",
]

_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def insert_indicators(df: pd.DataFrame):
    if df.empty:
        return
    df = df.where(pd.notnull(df), None)
    engine = get_connection()

    query = text(f"""
        INSERT INTO indicators_data ({_COL_LIST})
        VALUES ({_BIND_LIST})
        ON CONFLICT (symbol, date) DO NOTHING;
    """)

    records = df[_COLUMNS].to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(query, records)

def get_indicators(
    symbol: str | list[str],
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
):
    engine = get_connection()
    symbols = [symbol] if isinstance(symbol, str) else symbol

    query = f"""
        SELECT {_COL_LIST}
        FROM indicators_data
        WHERE symbol = ANY(:symbols)
    """

    params = {"symbols": symbols}

    if start_date is not None:
        query += " AND date >= :start_date"
        params["start_date"] = start_date

    if end_date is not None:
        query += " AND date <= :end_date"
        params["end_date"] = end_date

    query += " ORDER BY symbol ASC, date ASC"

    df = pd.read_sql_query(text(query), engine, params=params)

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])

    return df

def get_latest_date(symbols: str | list[str]) -> pd.DataFrame:
    """Returns DataFrame(symbol, latest_date) — the most recent date in the DB per symbol."""
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols
    query = text("""
        SELECT symbol, MAX(date) AS latest_date
        FROM indicators_data
        WHERE symbol = ANY(:symbols)
        GROUP BY symbol
    """)
    return pd.read_sql_query(query, engine, params={"symbols": symbols})


def get_latest_indicators(symbols: str | list[str], signal_day: pd.Timestamp):
    engine = get_connection()
    symbols = [symbols] if isinstance(symbols, str) else symbols

    query = f"""
        SELECT DISTINCT ON (symbol) {_COL_LIST}
        FROM indicators_data
        WHERE symbol = ANY(:symbols)
            AND date <= :signal_day
        ORDER BY symbol, date DESC
    """

    params = {
        "symbols": symbols,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }

    return pd.read_sql_query(text(query), engine, params=params)
