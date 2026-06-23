"""
Registry of active deterministic prefilters and their metadata / risk parameters.
Each row describes one versioned prefilter; the runner loads only active rows.
"""

from __future__ import annotations
from sqlalchemy import text
from database.db_connection import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS prefilter_profiles (
    profile_id          SERIAL PRIMARY KEY,
    name                VARCHAR(64)  NOT NULL,
    version             VARCHAR(16)  NOT NULL DEFAULT '1.0',
    description         TEXT,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,

    -- Risk envelope written into every candidate packet emitted by this prefilter
    default_holding_days    INT,
    max_position_pct        NUMERIC(6,4),   -- fraction of portfolio (e.g. 0.05 = 5 %)
    max_loss_pct            NUMERIC(6,4),   -- max drawdown allowed per trade
    allowed_stop_ids        TEXT[],         -- list of stop-choice IDs this prefilter permits
    allowed_target_ids      TEXT[],
    allowed_timeline_ids    TEXT[],

    -- Backtest / walk-forward summary (refreshed periodically)
    backtest_win_rate       NUMERIC(6,4),
    backtest_expectancy     NUMERIC(10,4),
    backtest_sharpe         NUMERIC(8,4),
    wf_win_rate             NUMERIC(6,4),
    wf_expectancy           NUMERIC(10,4),
    backtest_start_date     DATE,
    backtest_end_date       DATE,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (name, version)
);
"""


def create_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL))
        conn.commit()


def drop_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS prefilter_profiles CASCADE"))
        conn.commit()


def upsert_profile(row: dict) -> int:
    """Insert or update a prefilter profile. Returns profile_id."""
    sql = text("""
        INSERT INTO prefilter_profiles
            (name, version, description, is_active,
             default_holding_days, max_position_pct, max_loss_pct,
             allowed_stop_ids, allowed_target_ids, allowed_timeline_ids,
             backtest_win_rate, backtest_expectancy, backtest_sharpe,
             wf_win_rate, wf_expectancy, backtest_start_date, backtest_end_date)
        VALUES
            (:name, :version, :description, :is_active,
             :default_holding_days, :max_position_pct, :max_loss_pct,
             :allowed_stop_ids, :allowed_target_ids, :allowed_timeline_ids,
             :backtest_win_rate, :backtest_expectancy, :backtest_sharpe,
             :wf_win_rate, :wf_expectancy, :backtest_start_date, :backtest_end_date)
        ON CONFLICT (name, version) DO UPDATE SET
            description         = EXCLUDED.description,
            is_active           = EXCLUDED.is_active,
            default_holding_days= EXCLUDED.default_holding_days,
            max_position_pct    = EXCLUDED.max_position_pct,
            max_loss_pct        = EXCLUDED.max_loss_pct,
            allowed_stop_ids    = EXCLUDED.allowed_stop_ids,
            allowed_target_ids  = EXCLUDED.allowed_target_ids,
            allowed_timeline_ids= EXCLUDED.allowed_timeline_ids,
            backtest_win_rate   = EXCLUDED.backtest_win_rate,
            backtest_expectancy = EXCLUDED.backtest_expectancy,
            backtest_sharpe     = EXCLUDED.backtest_sharpe,
            wf_win_rate         = EXCLUDED.wf_win_rate,
            wf_expectancy       = EXCLUDED.wf_expectancy,
            backtest_start_date = EXCLUDED.backtest_start_date,
            backtest_end_date   = EXCLUDED.backtest_end_date,
            updated_at          = NOW()
        RETURNING profile_id
    """)
    with get_connection().connect() as conn:
        result = conn.execute(sql, row)
        conn.commit()
        return result.scalar_one()


def get_active_profiles() -> list[dict]:
    sql = text(
        "SELECT * FROM prefilter_profiles WHERE is_active = TRUE ORDER BY name, version"
    )
    with get_connection().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql)]


def get_profile(name: str, version: str = "1.0") -> dict | None:
    sql = text(
        "SELECT * FROM prefilter_profiles WHERE name = :name AND version = :version"
    )
    with get_connection().connect() as conn:
        row = conn.execute(sql, {"name": name, "version": version}).fetchone()
        return dict(row._mapping) if row else None
