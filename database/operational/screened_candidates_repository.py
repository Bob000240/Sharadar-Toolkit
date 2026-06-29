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

    -- Risk menu (deterministic). Each menu is a JSON array of choice objects with
    -- prices/levels resolved as of decision_date. Object shape per menu --
    --   stop      -> id, price, pct, label
    --   target    -> id, price, pct, rr
    --   timeline  -> id, days
    -- default_*_id points at one entry's id in the corresponding menu.
    stop_menu           JSONB,
    target_menu         JSONB,
    timeline_menu       JSONB,
    default_stop_id     VARCHAR(32),
    default_target_id   VARCHAR(32),
    default_timeline_id VARCHAR(32),
    default_holding_days INT,            -- resolved days for default_timeline_id
    max_position_pct    NUMERIC(6,4),
    max_loss_pct        NUMERIC(6,4),

    -- Decision-time context (frozen as of decision_date)
    entry_price         NUMERIC(12,4),
    market_regime       VARCHAR(32),     -- macro-overlay regime label for eval slicing
    macro_score         NUMERIC(6,4),

    -- Backtest context snapshot (frozen as of decision_date)
    backtest_win_rate   NUMERIC(6,4),
    backtest_expectancy NUMERIC(10,4),
    backtest_sharpe     NUMERIC(8,4),

    -- Raw signal payload + normalized vector for similar-setup retrieval
    signal_context      JSONB,
    feature_vector      VECTOR(64),

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (symbol, decision_date, profile_id)
);
CREATE INDEX IF NOT EXISTS idx_candidates_symbol_date
    ON screened_candidates (symbol, decision_date DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_profile
    ON screened_candidates (profile_id, decision_date DESC);
"""

DDL_VECTOR_INDEX = """
CREATE INDEX IF NOT EXISTS idx_candidates_feature_vector
    ON screened_candidates USING ivfflat (feature_vector vector_cosine_ops)
    WITH (lists = 100);
"""


def create_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL))
        conn.commit()


def drop_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS screened_candidates CASCADE"))
        conn.commit()


def create_vector_index() -> None:
    """Run after the table is populated (ivfflat needs data to build lists)."""
    with get_connection().connect() as conn:
        conn.execute(text(DDL_VECTOR_INDEX))
        conn.commit()


def insert_candidate(row: dict) -> int:
    """Insert or replace a candidate packet. Returns candidate_id."""
    row = dict(row)
    for col in ("signal_context", "stop_menu", "target_menu", "timeline_menu"):
        if isinstance(row.get(col), (dict, list)):
            row[col] = json.dumps(row[col])
    if isinstance(row.get("feature_vector"), (list, tuple)):
        row["feature_vector"] = str(list(row["feature_vector"]))

    sql = text("""
        INSERT INTO screened_candidates
            (symbol, decision_date, profile_id,
             setup_score, passed_gates, risk_flags,
             stop_menu, target_menu, timeline_menu,
             default_stop_id, default_target_id, default_timeline_id,
             default_holding_days, max_position_pct, max_loss_pct,
             entry_price, market_regime, macro_score,
             backtest_win_rate, backtest_expectancy, backtest_sharpe,
             signal_context, feature_vector)
        VALUES
            (:symbol, :decision_date, :profile_id,
             :setup_score, :passed_gates, :risk_flags,
             CAST(:stop_menu AS jsonb), CAST(:target_menu AS jsonb),
             CAST(:timeline_menu AS jsonb),
             :default_stop_id, :default_target_id, :default_timeline_id,
             :default_holding_days, :max_position_pct, :max_loss_pct,
             :entry_price, :market_regime, :macro_score,
             :backtest_win_rate, :backtest_expectancy, :backtest_sharpe,
             CAST(:signal_context AS jsonb), CAST(:feature_vector AS vector))
        ON CONFLICT (symbol, decision_date, profile_id) DO UPDATE SET
            setup_score          = EXCLUDED.setup_score,
            passed_gates         = EXCLUDED.passed_gates,
            risk_flags           = EXCLUDED.risk_flags,
            stop_menu            = EXCLUDED.stop_menu,
            target_menu          = EXCLUDED.target_menu,
            timeline_menu        = EXCLUDED.timeline_menu,
            default_stop_id      = EXCLUDED.default_stop_id,
            default_target_id    = EXCLUDED.default_target_id,
            default_timeline_id  = EXCLUDED.default_timeline_id,
            default_holding_days = EXCLUDED.default_holding_days,
            max_position_pct     = EXCLUDED.max_position_pct,
            max_loss_pct         = EXCLUDED.max_loss_pct,
            entry_price          = EXCLUDED.entry_price,
            market_regime        = EXCLUDED.market_regime,
            macro_score          = EXCLUDED.macro_score,
            backtest_win_rate    = EXCLUDED.backtest_win_rate,
            backtest_expectancy  = EXCLUDED.backtest_expectancy,
            backtest_sharpe      = EXCLUDED.backtest_sharpe,
            signal_context       = EXCLUDED.signal_context,
            feature_vector       = EXCLUDED.feature_vector
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
