"""
Agent verdicts, tool calls, evidence, and selected trade plans.
Includes a pgvector column for numeric feature-vector similarity search.
"""

from __future__ import annotations
import json
from datetime import date
from sqlalchemy import text
from database.db_connection import get_connection

DDL_MEMORY = """
CREATE TABLE IF NOT EXISTS decision_memory (
    memory_id           SERIAL PRIMARY KEY,
    candidate_id        INT          REFERENCES screened_candidates(candidate_id),
    symbol              VARCHAR(16)  NOT NULL,
    decision_date       DATE         NOT NULL,
    profile_id          INT          REFERENCES prefilter_profiles(profile_id),

    -- Agent verdict
    decision            VARCHAR(16)  NOT NULL CHECK (decision IN ('ACCEPT','REJECT')),
    conviction_tier     VARCHAR(16)  CHECK (conviction_tier IN
                            ('HIGH_CONVICTION','CONVICTION','LOW_CONVICTION')),
    selected_stop_id    VARCHAR(32),
    selected_target_id  VARCHAR(32),
    selected_timeline_id VARCHAR(32),
    profit_likelihood   NUMERIC(5,4),   -- 0.0–1.0
    confidence          NUMERIC(5,4),   -- 0.0–1.0
    rationale           TEXT,

    -- Evidence / tool calls
    tools_called        TEXT[],
    evidence_ids        TEXT[],
    tool_call_log       JSONB,

    -- Outcome (written back after trade resolves)
    resolved            BOOLEAN      NOT NULL DEFAULT FALSE,
    resolution_date     DATE,
    outcome_pnl_pct     NUMERIC(10,6),
    outcome_hit_target  BOOLEAN,
    outcome_hit_stop    BOOLEAN,
    outcome_days_held   INT,

    -- Feature vector for similarity search (pgvector)
    feature_vector      VECTOR(64),

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memory_symbol_date
    ON decision_memory (symbol, decision_date DESC);
CREATE INDEX IF NOT EXISTS idx_memory_resolved
    ON decision_memory (resolved, resolution_date DESC);
"""

DDL_VECTOR_INDEX = """
CREATE INDEX IF NOT EXISTS idx_memory_feature_vector
    ON decision_memory USING ivfflat (feature_vector vector_cosine_ops)
    WITH (lists = 100);
"""


def create_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text(DDL_MEMORY))
        conn.commit()


def create_vector_index() -> None:
    """Run after table is populated (ivfflat needs data to build lists)."""
    with get_connection().connect() as conn:
        conn.execute(text(DDL_VECTOR_INDEX))
        conn.commit()


def drop_table() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS decision_memory CASCADE"))
        conn.commit()


def insert_decision(row: dict) -> int:
    if "tool_call_log" in row and isinstance(row["tool_call_log"], (dict, list)):
        row = {**row, "tool_call_log": json.dumps(row["tool_call_log"])}

    sql = text("""
        INSERT INTO decision_memory
            (candidate_id, symbol, decision_date, profile_id,
             decision, conviction_tier,
             selected_stop_id, selected_target_id, selected_timeline_id,
             profit_likelihood, confidence, rationale,
             tools_called, evidence_ids, tool_call_log,
             feature_vector)
        VALUES
            (:candidate_id, :symbol, :decision_date, :profile_id,
             :decision, :conviction_tier,
             :selected_stop_id, :selected_target_id, :selected_timeline_id,
             :profit_likelihood, :confidence, :rationale,
             :tools_called, :evidence_ids, :tool_call_log::jsonb,
             :feature_vector)
        RETURNING memory_id
    """)
    with get_connection().connect() as conn:
        result = conn.execute(sql, row)
        conn.commit()
        return result.scalar_one()


def record_outcome(memory_id: int, outcome: dict) -> None:
    sql = text("""
        UPDATE decision_memory SET
            resolved           = TRUE,
            resolution_date    = :resolution_date,
            outcome_pnl_pct    = :outcome_pnl_pct,
            outcome_hit_target = :outcome_hit_target,
            outcome_hit_stop   = :outcome_hit_stop,
            outcome_days_held  = :outcome_days_held,
            updated_at         = NOW()
        WHERE memory_id = :memory_id
    """)
    with get_connection().connect() as conn:
        conn.execute(sql, {"memory_id": memory_id, **outcome})
        conn.commit()


def get_resolved_decisions(
    before_date: date,
    profile_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return resolved decisions strictly before decision_date (point-in-time safe)."""
    if profile_id is not None:
        sql = text("""
            SELECT * FROM decision_memory
            WHERE resolved = TRUE
              AND resolution_date < :d
              AND profile_id = :pid
            ORDER BY resolution_date DESC
            LIMIT :lim
        """)
        params = {"d": before_date, "pid": profile_id, "lim": limit}
    else:
        sql = text("""
            SELECT * FROM decision_memory
            WHERE resolved = TRUE AND resolution_date < :d
            ORDER BY resolution_date DESC
            LIMIT :lim
        """)
        params = {"d": before_date, "lim": limit}

    with get_connection().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sql, params)]


def search_similar(
    vector: list[float], before_date: date, limit: int = 10
) -> list[dict]:
    """Cosine similarity search over feature vectors (requires pgvector)."""
    sql = text("""
        SELECT *, 1 - (feature_vector <=> :vec::vector) AS similarity
        FROM decision_memory
        WHERE resolved = TRUE
          AND resolution_date < :d
          AND feature_vector IS NOT NULL
        ORDER BY feature_vector <=> :vec::vector
        LIMIT :lim
    """)
    with get_connection().connect() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                sql, {"vec": str(vector), "d": before_date, "lim": limit}
            )
        ]
