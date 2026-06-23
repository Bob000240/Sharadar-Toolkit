"""
Realized outcomes for accepted trades.
Written back after each position is closed; feeds the eval harness.
"""

from __future__ import annotations
from datetime import date
from sqlalchemy import text
from database.db_connection import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS trade_outcomes (
    outcome_id          SERIAL PRIMARY KEY,
    memory_id           INT          REFERENCES decision_memory(memory_id),
    candidate_id        INT          REFERENCES screened_candidates(candidate_id),
    symbol              VARCHAR(16)  NOT NULL,
    profile_id          INT          REFERENCES prefilter_profiles(profile_id),
    decision_date       DATE         NOT NULL,

    -- Execution details
    entry_date          DATE,
    exit_date           DATE,
    entry_price         NUMERIC(12,4),
    exit_price          NUMERIC(12,4),
    shares              NUMERIC(14,4),
    position_size_pct   NUMERIC(6,4),   -- fraction of portfolio at entry

    -- Agent choices
    conviction_tier     VARCHAR(16),
    selected_stop_id    VARCHAR(32),
    selected_target_id  VARCHAR(32),
    selected_timeline_id VARCHAR(32),
    selected_stop_price  NUMERIC(12,4),
    selected_target_price NUMERIC(12,4),

    -- Default / deterministic baselines (for eval comparison)
    default_stop_id     VARCHAR(32),
    default_target_id   VARCHAR(32),
    default_timeline_id VARCHAR(32),
    default_stop_price  NUMERIC(12,4),
    default_target_price NUMERIC(12,4),
    default_size_pct    NUMERIC(6,4),

    -- Realized outcomes
    gross_pnl           NUMERIC(14,4),
    gross_pnl_pct       NUMERIC(10,6),
    days_held           INT,
    exit_reason         VARCHAR(32),    -- TARGET_HIT, STOP_HIT, TIMELINE_HIT, MANUAL

    -- Benchmark comparison
    benchmark_return_pct NUMERIC(10,6),
    excess_return_pct    NUMERIC(10,6),

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_outcomes_profile_date
    ON trade_outcomes (profile_id, exit_date DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_symbol
    ON trade_outcomes (symbol, exit_date DESC);
"""


def create_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL))
        conn.commit()


def drop_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS trade_outcomes CASCADE"))
        conn.commit()


def insert_outcome(row: dict) -> int:
    sql = text("""
        INSERT INTO trade_outcomes
            (memory_id, candidate_id, symbol, profile_id, decision_date,
             entry_date, exit_date, entry_price, exit_price, shares, position_size_pct,
             conviction_tier, selected_stop_id, selected_target_id, selected_timeline_id,
             selected_stop_price, selected_target_price,
             default_stop_id, default_target_id, default_timeline_id,
             default_stop_price, default_target_price, default_size_pct,
             gross_pnl, gross_pnl_pct, days_held, exit_reason,
             benchmark_return_pct, excess_return_pct)
        VALUES
            (:memory_id, :candidate_id, :symbol, :profile_id, :decision_date,
             :entry_date, :exit_date, :entry_price, :exit_price, :shares, :position_size_pct,
             :conviction_tier, :selected_stop_id, :selected_target_id, :selected_timeline_id,
             :selected_stop_price, :selected_target_price,
             :default_stop_id, :default_target_id, :default_timeline_id,
             :default_stop_price, :default_target_price, :default_size_pct,
             :gross_pnl, :gross_pnl_pct, :days_held, :exit_reason,
             :benchmark_return_pct, :excess_return_pct)
        RETURNING outcome_id
    """)
    with get_connection().connect() as conn:
        result = conn.execute(sql, row)
        conn.commit()
        return result.scalar_one()


def get_outcomes_by_profile(
    profile_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    sql = text("""
        SELECT * FROM trade_outcomes
        WHERE profile_id = :pid
          AND (:start IS NULL OR exit_date >= :start)
          AND (:end   IS NULL OR exit_date <= :end)
        ORDER BY exit_date DESC
    """)
    with get_connection().connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                sql, {"pid": profile_id, "start": start_date, "end": end_date}
            )
        ]


def get_profile_summary(profile_id: int) -> dict:
    sql = text("""
        SELECT
            COUNT(*)                            AS total_trades,
            AVG(gross_pnl_pct)                  AS avg_return_pct,
            SUM(CASE WHEN gross_pnl_pct > 0 THEN 1 ELSE 0 END)::FLOAT
                / NULLIF(COUNT(*), 0)            AS win_rate,
            AVG(excess_return_pct)              AS avg_alpha,
            MIN(gross_pnl_pct)                  AS max_loss_pct,
            MAX(gross_pnl_pct)                  AS max_gain_pct
        FROM trade_outcomes
        WHERE profile_id = :pid
    """)
    with get_connection().connect() as conn:
        row = conn.execute(sql, {"pid": profile_id}).fetchone()
        return dict(row._mapping) if row else {}
