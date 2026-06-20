"""initial schema — base tables (formerly created by repository DDL functions)

Captures the seven tables that were previously created ad-hoc by
``create_*_table`` functions scattered across ``database/*_repository.py``.
DDL now lives here, versioned. TimescaleDB hypertables, pgvector, and the
platform tables (setups / eval_runs / backtest_*) are added in later
migrations so this baseline stays portable to any vanilla PostgreSQL.

Revision ID: 0001
Revises:
Create Date: 2026-06-20
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            PRIMARY KEY (symbol, date)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS indicators_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,

            -- Price
            close DOUBLE PRECISION,

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
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_descriptors (
            symbol       TEXT PRIMARY KEY,
            company_name TEXT,
            sector       TEXT,
            industry     TEXT,
            country      TEXT,
            exchange     TEXT,
            currency     TEXT,
            market_cap   NUMERIC,
            size_bucket  TEXT,
            is_etf       BOOLEAN
        );
        """
    )

    op.execute(
        """
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
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS value_fundamentals (
            symbol              TEXT NOT NULL,
            date                DATE NOT NULL,
            pe_ratio            DOUBLE PRECISION,
            earnings_yield      DOUBLE PRECISION,
            pb_ratio            DOUBLE PRECISION,
            price_to_sales      DOUBLE PRECISION,
            ev_ebitda           DOUBLE PRECISION,
            ev_sales            DOUBLE PRECISION,
            ev_fcf              DOUBLE PRECISION,
            price_to_fcf        DOUBLE PRECISION,
            fcf_yield           DOUBLE PRECISION,
            dividend_yield      DOUBLE PRECISION,
            PRIMARY KEY (symbol, date)
        );
        """
    )

    op.execute(
        """
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
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_data (
            date DATE PRIMARY KEY,
            yield_10y DOUBLE PRECISION,
            yield_2y DOUBLE PRECISION,
            yield_curve DOUBLE PRECISION,
            real_yield DOUBLE PRECISION,
            cpi_yoy DOUBLE PRECISION,
            unemployment_rate DOUBLE PRECISION,
            credit_spread_hy DOUBLE PRECISION,
            credit_spread_ig DOUBLE PRECISION,
            vix DOUBLE PRECISION
        );
        """
    )


def downgrade() -> None:
    for table in (
        "macro_data",
        "growth_fundamentals",
        "value_fundamentals",
        "quality_fundamentals",
        "stock_descriptors",
        "indicators_data",
        "ohlcv_data",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table};")
