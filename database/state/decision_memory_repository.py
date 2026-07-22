"""Completed trades used as the agent's historical decision memory.

Open positions live in positions.json. When a position closes, its complete record
is inserted here once. Rejected candidates and risk-blocked candidates are not stored.
"""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID

from sqlalchemy import text

from database.db_connection import get_connection


DDL = """
CREATE TABLE IF NOT EXISTS decision_memory (
    -- Identity and the original candidate shown to the agent.
    trade_id UUID PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    strategy_name VARCHAR(64) NOT NULL REFERENCES strategy_profiles(name),
    candidate_snapshot JSONB NOT NULL,

    -- Agent context recorded when the position opened.
    conviction_tier VARCHAR(24) NOT NULL CHECK (
        conviction_tier IN ('HIGH_CONVICTION', 'CONVICTION', 'LOW_CONVICTION')
    ),
    rationale TEXT NOT NULL,
    evidence JSONB,
    tool_call_log JSONB,

    -- Actual entry execution.
    entry_date DATE NOT NULL,
    entry_price NUMERIC(12,4) NOT NULL,
    position_size_pct NUMERIC(6,4) NOT NULL,

    -- Actual final outcome.
    exit_date DATE NOT NULL,
    exit_price NUMERIC(12,4) NOT NULL,
    realized_pnl_pct NUMERIC(10,6) NOT NULL,
    days_held INT NOT NULL,
    exit_reason VARCHAR(32) NOT NULL CHECK (
        exit_reason IN ('MAXIMUM_LOSS_BREACH', 'THESIS_INVALIDATED', 'CONCERNING_EVENTS')
    ),
    -- Which specific rule fired within the reason, its trigger values, and (for
    -- an agent exit) the cited source. Mirrors signal_context on the entry side.
    exit_context JSONB,

    -- Embedding of the completed trade for similar-trade retrieval.
    -- The column is dimensionless until one embedding method is selected.
    decision_embedding VECTOR NOT NULL,

    CHECK (exit_date >= entry_date),
    CHECK (entry_price > 0),
    CHECK (exit_price > 0),
    CHECK (position_size_pct > 0 AND position_size_pct <= 1),
    CHECK (days_held >= 0)
);

CREATE INDEX IF NOT EXISTS idx_decision_memory_symbol_exit
    ON decision_memory (symbol, exit_date DESC);
CREATE INDEX IF NOT EXISTS idx_decision_memory_strategy_exit
    ON decision_memory (strategy_name, exit_date DESC);
"""


def create_table() -> None:
    with get_connection().begin() as conn:
        conn.execute(text(DDL))


def drop_table() -> None:
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS decision_memory CASCADE"))


def insert_trade(row: dict) -> UUID:
    """Insert one completed trade and return its existing trade_id."""
    row = dict(row)
    for key in ("candidate_snapshot", "evidence", "tool_call_log", "exit_context"):
        if isinstance(row.get(key), (dict, list)):
            row[key] = json.dumps(row[key])
    if isinstance(row.get("decision_embedding"), (list, tuple)):
        row["decision_embedding"] = str(list(row["decision_embedding"]))

    sql = text("""
        INSERT INTO decision_memory
            (trade_id, symbol, strategy_name, candidate_snapshot,
             conviction_tier, rationale, evidence, tool_call_log,
             entry_date, entry_price, position_size_pct,
             exit_date, exit_price, realized_pnl_pct, days_held,
             exit_reason, exit_context, decision_embedding)
        VALUES
            (:trade_id, :symbol, :strategy_name,
             CAST(:candidate_snapshot AS jsonb),
             :conviction_tier, :rationale, CAST(:evidence AS jsonb),
             CAST(:tool_call_log AS jsonb),
             :entry_date, :entry_price, :position_size_pct,
             :exit_date, :exit_price, :realized_pnl_pct, :days_held,
             :exit_reason, CAST(:exit_context AS jsonb), CAST(:decision_embedding AS vector))
        RETURNING trade_id
    """)
    with get_connection().begin() as conn:
        return conn.execute(sql, row).scalar_one()


def get_trade(trade_id: UUID) -> dict | None:
    sql = text("SELECT * FROM decision_memory WHERE trade_id = :trade_id")
    with get_connection().connect() as conn:
        row = conn.execute(sql, {"trade_id": trade_id}).fetchone()
        return dict(row._mapping) if row else None


def get_prior_trades(
    before_date: date,
    strategy_name: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return only trades whose outcomes were known before before_date."""
    if strategy_name is None:
        sql = text("""
            SELECT * FROM decision_memory
            WHERE exit_date < :before_date
            ORDER BY exit_date DESC
            LIMIT :limit
        """)
        params = {"before_date": before_date, "limit": limit}
    else:
        sql = text("""
            SELECT * FROM decision_memory
            WHERE exit_date < :before_date
              AND strategy_name = :strategy_name
            ORDER BY exit_date DESC
            LIMIT :limit
        """)
        params = {
            "before_date": before_date,
            "strategy_name": strategy_name,
            "limit": limit,
        }

    with get_connection().connect() as conn:
        return [dict(row._mapping) for row in conn.execute(sql, params)]


def search_similar_trades(
    embedding: list[float],
    before_date: date,
    limit: int = 10,
) -> list[dict]:
    """Find similar completed trades without exposing future outcomes."""
    sql = text("""
        SELECT *,
               1 - (decision_embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM decision_memory
        WHERE exit_date < :before_date
        ORDER BY decision_embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)
    params = {
        "embedding": str(embedding),
        "before_date": before_date,
        "limit": limit,
    }
    with get_connection().connect() as conn:
        return [dict(row._mapping) for row in conn.execute(sql, params)]
