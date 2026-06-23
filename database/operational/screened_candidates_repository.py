"""
Passing candidate packets emitted by deterministic prefilters.
One row per (symbol, decision_date, profile_id) combination.
"""

from __future__ import annotations
import json
from datetime import date
from sqlalchemy import text
from database.db_connection import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS screened_candidates (
    candidate_id        SERIAL PRIMARY KEY,
    symbol              VARCHAR(16)  NOT NULL,
    decision_date       DATE         NOT NULL,
    profile_id          INT          NOT NULL REFERENCES prefilter_profiles(profile_id),

    -- Signal summary
    setup_score         NUMERIC(8,4),
    passed_gates        TEXT[],
    risk_flags          TEXT[],

    -- Risk menu (deterministic — agent may only choose within these)
    default_stop_id     VARCHAR(32),
    default_target_id   VARCHAR(32),
    default_timeline_id VARCHAR(32),
    allowed_stop_ids    TEXT[],
    allowed_target_ids  TEXT[],
    allowed_timeline_ids TEXT[],
    max_position_pct    NUMERIC(6,4),
    max_loss_pct        NUMERIC(6,4),

    -- Prices at decision time
    entry_price         NUMERIC(12,4),
    default_stop_price  NUMERIC(12,4),
    default_target_price NUMERIC(12,4),

    -- Backtest context snapshot
    backtest_win_rate   NUMERIC(6,4),
    backtest_expectancy NUMERIC(10,4),

    -- Raw signal payload (full feature vector for retrieval)
    signal_context      JSONB,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (symbol, decision_date, profile_id)
);
CREATE INDEX IF NOT EXISTS idx_candidates_symbol_date
    ON screened_candidates (symbol, decision_date DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_profile
    ON screened_candidates (profile_id, decision_date DESC);
"""


def create_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL))
        conn.commit()


def drop_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS screened_candidates CASCADE"))
        conn.commit()


def insert_candidate(row: dict) -> int:
    """Insert or replace a candidate packet. Returns candidate_id."""
    if "signal_context" in row and isinstance(row["signal_context"], dict):
        row = {**row, "signal_context": json.dumps(row["signal_context"])}

    sql = text("""
        INSERT INTO screened_candidates
            (symbol, decision_date, profile_id,
             setup_score, passed_gates, risk_flags,
             default_stop_id, default_target_id, default_timeline_id,
             allowed_stop_ids, allowed_target_ids, allowed_timeline_ids,
             max_position_pct, max_loss_pct,
             entry_price, default_stop_price, default_target_price,
             backtest_win_rate, backtest_expectancy, signal_context)
        VALUES
            (:symbol, :decision_date, :profile_id,
             :setup_score, :passed_gates, :risk_flags,
             :default_stop_id, :default_target_id, :default_timeline_id,
             :allowed_stop_ids, :allowed_target_ids, :allowed_timeline_ids,
             :max_position_pct, :max_loss_pct,
             :entry_price, :default_stop_price, :default_target_price,
             :backtest_win_rate, :backtest_expectancy, :signal_context::jsonb)
        ON CONFLICT (symbol, decision_date, profile_id) DO UPDATE SET
            setup_score         = EXCLUDED.setup_score,
            passed_gates        = EXCLUDED.passed_gates,
            risk_flags          = EXCLUDED.risk_flags,
            default_stop_price  = EXCLUDED.default_stop_price,
            default_target_price= EXCLUDED.default_target_price,
            signal_context      = EXCLUDED.signal_context
        RETURNING candidate_id
    """)
    with get_connection().connect() as conn:
        result = conn.execute(sql, row)
        conn.commit()
        return result.scalar_one()


def get_candidates(decision_date: date, profile_id: int | None = None) -> list[dict]:
    if profile_id is not None:
        sql = text("""
            SELECT * FROM screened_candidates
            WHERE decision_date = :d AND profile_id = :pid
            ORDER BY setup_score DESC NULLS LAST
        """)
        params = {"d": decision_date, "pid": profile_id}
    else:
        sql = text("""
            SELECT * FROM screened_candidates
            WHERE decision_date = :d
            ORDER BY setup_score DESC NULLS LAST
        """)
        params = {"d": decision_date}

    with get_connection().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql, params)]


def get_candidate(symbol: str, decision_date: date, profile_id: int) -> dict | None:
    sql = text("""
        SELECT * FROM screened_candidates
        WHERE symbol = :sym AND decision_date = :d AND profile_id = :pid
    """)
    with get_connection().connect() as conn:
        row = conn.execute(
            sql, {"sym": symbol, "d": decision_date, "pid": profile_id}
        ).fetchone()
        return dict(row._mapping) if row else None
