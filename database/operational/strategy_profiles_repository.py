"""Read-only access to deterministic strategy profiles.

The fixed strategy suite is seeded during database setup. Normal strategy runs only
read these rows; executable strategy selection remains code-owned.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from database.db_connection import get_connection


DEFAULT_CONVICTION = {
    "HIGH_CONVICTION": 1.0,
    "CONVICTION": 0.6,
    "LOW_CONVICTION": 0.3,
}

STRATEGY_PROFILES = (
    {
        "name": "momentum",
        "description": "Relative-strength / trend-continuation on liquid US equities.",
        "max_position_pct": 0.05,
        "max_loss_pct": 0.10,
        "conviction_size_multipliers": DEFAULT_CONVICTION,
    },
    {
        "name": "value",
        "description": "Sector-relative deep value with a Piotroski trap filter.",
        "max_position_pct": 0.05,
        "max_loss_pct": 0.15,
        "conviction_size_multipliers": DEFAULT_CONVICTION,
    },
    {
        "name": "quality",
        "description": "High-quality compounders on liquid US equities (late-cycle tilt).",
        "max_position_pct": 0.06,
        "max_loss_pct": 0.12,
        "conviction_size_multipliers": DEFAULT_CONVICTION,
    },
)

DDL = """
CREATE TABLE IF NOT EXISTS strategy_profiles (
    profile_id SERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE,
    description TEXT,
    max_position_pct NUMERIC(6,4) NOT NULL,
    max_loss_pct NUMERIC(6,4) NOT NULL,
    conviction_size_multipliers JSONB NOT NULL
);
"""


def create_table() -> None:
    """Create and seed the fixed profiles during database setup."""
    seed_sql = text("""
        INSERT INTO strategy_profiles
            (name, description, max_position_pct, max_loss_pct,
             conviction_size_multipliers)
        VALUES
            (:name, :description, :max_position_pct, :max_loss_pct,
             CAST(:conviction_size_multipliers AS jsonb))
        ON CONFLICT (name) DO NOTHING
    """)
    with get_connection().begin() as conn:
        conn.execute(text(DDL))
        conn.execute(
            seed_sql,
            [
                {
                    **profile,
                    "conviction_size_multipliers": json.dumps(
                        profile["conviction_size_multipliers"]
                    ),
                }
                for profile in STRATEGY_PROFILES
            ],
        )


def drop_table() -> None:
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS strategy_profiles CASCADE"))


def get_profile(profile_id: int) -> dict | None:
    sql = text("SELECT * FROM strategy_profiles WHERE profile_id = :profile_id")
    with get_connection().connect() as conn:
        row = conn.execute(sql, {"profile_id": profile_id}).fetchone()
        return dict(row._mapping) if row else None


def get_profile_by_name(name: str) -> dict | None:
    sql = text("SELECT * FROM strategy_profiles WHERE name = :name")
    with get_connection().connect() as conn:
        row = conn.execute(sql, {"name": name}).fetchone()
        return dict(row._mapping) if row else None
