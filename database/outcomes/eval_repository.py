"""
Stored evaluation runs — agent vs deterministic baseline comparisons.
"""

from __future__ import annotations
import json
from datetime import date
from sqlalchemy import text
from database.db_connection import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS eval_results (
    eval_id             SERIAL PRIMARY KEY,
    run_label           VARCHAR(128) NOT NULL,
    profile_id          INT          REFERENCES prefilter_profiles(profile_id),
    eval_start_date     DATE,
    eval_end_date       DATE,
    run_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Trade count
    total_trades        INT,
    accepted_trades     INT,
    rejected_trades     INT,

    -- Agent outcome metrics
    agent_win_rate      NUMERIC(6,4),
    agent_avg_return    NUMERIC(10,6),
    agent_expectancy    NUMERIC(10,6),
    agent_sharpe        NUMERIC(8,4),
    agent_max_drawdown  NUMERIC(8,4),

    -- Deterministic baseline metrics (what default stop/target/size would have done)
    base_win_rate       NUMERIC(6,4),
    base_avg_return     NUMERIC(10,6),
    base_expectancy     NUMERIC(10,6),
    base_sharpe         NUMERIC(8,4),
    base_max_drawdown   NUMERIC(8,4),

    -- Lift
    lift_win_rate       NUMERIC(8,4),   -- agent - base
    lift_expectancy     NUMERIC(10,6),
    lift_sharpe         NUMERIC(8,4),

    -- Stop / target / timeline selection analysis
    stop_match_rate     NUMERIC(6,4),   -- fraction choosing default stop
    target_match_rate   NUMERIC(6,4),
    timeline_match_rate NUMERIC(6,4),

    -- Conviction calibration
    avg_profit_likelihood NUMERIC(6,4),
    calibration_error   NUMERIC(8,4),   -- mean |predicted - actual|

    -- Full metrics blob for ad-hoc analysis
    metrics_json        JSONB,

    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_profile
    ON eval_results (profile_id, run_at DESC);
"""


def create_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL))
        conn.commit()


def drop_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS eval_results CASCADE"))
        conn.commit()


def insert_eval(row: dict) -> int:
    if "metrics_json" in row and isinstance(row["metrics_json"], (dict, list)):
        row = {**row, "metrics_json": json.dumps(row["metrics_json"])}

    sql = text("""
        INSERT INTO eval_results
            (run_label, profile_id, eval_start_date, eval_end_date,
             total_trades, accepted_trades, rejected_trades,
             agent_win_rate, agent_avg_return, agent_expectancy,
             agent_sharpe, agent_max_drawdown,
             base_win_rate, base_avg_return, base_expectancy,
             base_sharpe, base_max_drawdown,
             lift_win_rate, lift_expectancy, lift_sharpe,
             stop_match_rate, target_match_rate, timeline_match_rate,
             avg_profit_likelihood, calibration_error,
             metrics_json, notes)
        VALUES
            (:run_label, :profile_id, :eval_start_date, :eval_end_date,
             :total_trades, :accepted_trades, :rejected_trades,
             :agent_win_rate, :agent_avg_return, :agent_expectancy,
             :agent_sharpe, :agent_max_drawdown,
             :base_win_rate, :base_avg_return, :base_expectancy,
             :base_sharpe, :base_max_drawdown,
             :lift_win_rate, :lift_expectancy, :lift_sharpe,
             :stop_match_rate, :target_match_rate, :timeline_match_rate,
             :avg_profit_likelihood, :calibration_error,
             :metrics_json::jsonb, :notes)
        RETURNING eval_id
    """)
    with get_connection().connect() as conn:
        result = conn.execute(sql, row)
        conn.commit()
        return result.scalar_one()


def get_recent_evals(profile_id: int | None = None, limit: int = 20) -> list[dict]:
    if profile_id is not None:
        sql = text("""
            SELECT * FROM eval_results
            WHERE profile_id = :pid
            ORDER BY run_at DESC LIMIT :lim
        """)
        params = {"pid": profile_id, "lim": limit}
    else:
        sql = text("SELECT * FROM eval_results ORDER BY run_at DESC LIMIT :lim")
        params = {"lim": limit}
    with get_connection().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql, params)]
