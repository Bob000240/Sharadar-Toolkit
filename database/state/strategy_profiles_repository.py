"""Strategy-profile descriptor rows: {name, description, active}.

A profile is a thin registry entry — the FK anchor for decision_memory and a
human/agent-readable label. It holds no strategy logic or sizing: conditions are
the strategy's code, sizing is the portfolio manager's. Rows are written by
`pipeline.main register/retire` from each strategy's NAME/DESCRIPTION constants,
not seeded here.
"""

from __future__ import annotations

from sqlalchemy import text

from database.db_connection import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS strategy_profiles (
    name VARCHAR(64) PRIMARY KEY,
    description TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE
);
"""


def create_table() -> None:
    with get_connection().begin() as conn:
        conn.execute(text(DDL))


def drop_table() -> None:
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS strategy_profiles CASCADE"))


def upsert_profile(name: str, description: str) -> None:
    """Register (or re-register) a strategy. Idempotent; reactivates a retired one."""
    sql = text("""
        INSERT INTO strategy_profiles (name, description, active)
        VALUES (:name, :description, TRUE)
        ON CONFLICT (name) DO UPDATE
            SET description = EXCLUDED.description,
                active = TRUE
    """)
    with get_connection().begin() as conn:
        conn.execute(sql, {"name": name, "description": description})


def retire_profile(name: str) -> bool:
    """Soft-retire: mark inactive so no new entries run. The row is kept — it
    anchors the strategy's historical decision_memory trades, so it must outlive
    them. Returns False if no such profile exists."""
    sql = text("UPDATE strategy_profiles SET active = FALSE WHERE name = :name")
    with get_connection().begin() as conn:
        return conn.execute(sql, {"name": name}).rowcount > 0


def get_profile_by_name(name: str) -> dict | None:
    sql = text("SELECT * FROM strategy_profiles WHERE name = :name")
    with get_connection().connect() as conn:
        row = conn.execute(sql, {"name": name}).fetchone()
        return dict(row._mapping) if row else None
