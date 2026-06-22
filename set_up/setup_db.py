"""
Master database setup script.
Drops all tables, enables pgvector, then recreates everything in dependency order.

Run once before load_data.py:
    python set_up/setup_db.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database.db_connection import get_connection

import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
import database.descriptors_repository as descriptor_repo
import database.fundamentals_repository as fund_repo
import database.institutional_repository as inst_repo
import database.market_metrics_repository as mm_repo
import database.prefilter_profiles_repository as profile_repo
import database.screened_candidates_repository as candidates_repo
import database.decision_memory_repository as memory_repo
import database.trade_outcomes_repository as outcomes_repo
import database.eval_repository as eval_repo


def _enable_pgvector() -> None:
    with get_connection().connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    print("pgvector extension enabled")


def _drop_all() -> None:
    """Drop all tables in reverse dependency order."""
    drops = [
        # System / eval
        "eval_results",
        "trade_outcomes",
        "decision_memory",
        "screened_candidates",
        "prefilter_profiles",
        # Market metrics (DAILY / METRICS / EVENTS / ACTIONS / SP500 / SFP)
        "fund_prices",
        "sp500_membership",
        "corporate_actions",
        "corporate_events",
        "market_metrics",
        "daily_metrics",
        # Institutional
        "institutional_investors",
        "institutional_summary",
        "institutional_holdings",
        "insider_transactions",
        # Core data
        "fundamentals",
        "stock_descriptors",
        # Legacy fundamentals (safe to drop even if already gone)
        "quality_fundamentals",
        "value_fundamentals",
        "growth_fundamentals",
        # OHLCV / indicators
        "indicators_data",
        "OHLCV_data",
        # Macro
        "macro_data",
    ]
    with get_connection().connect() as conn:
        for tbl in drops:
            conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))
            print(f"  dropped {tbl}")
        conn.commit()
    print("All tables dropped")


def _create_all() -> None:
    # 1. OHLCV and indicators (Alpaca-sourced, unchanged)
    market_repo.create_OHLCV_table()
    print("  created OHLCV_data")

    indicator_repo.create_indicators_table()
    print("  created indicators_data")

    # 2. Descriptors (Sharadar TICKERS)
    descriptor_repo.create_descriptors_table()
    print("  created stock_descriptors")

    # 3. Fundamentals (Sharadar SF1 — unified table)
    fund_repo.create_table()
    print("  created fundamentals")

    # 4. Institutional (SF2, SF3, SF3A, SF3B)
    inst_repo.create_tables()
    print("  created insider_transactions, institutional_holdings, institutional_summary, institutional_investors")

    # 5. Market metrics (DAILY, METRICS, EVENTS, ACTIONS, SP500, SFP)
    mm_repo.create_tables()
    print("  created daily_metrics, market_metrics, corporate_events, corporate_actions, sp500_membership, fund_prices")

    # 6. System tables (dependency order: profiles → candidates → memory → outcomes → eval)
    profile_repo.create_table()
    print("  created prefilter_profiles")

    candidates_repo.create_table()
    print("  created screened_candidates")

    memory_repo.create_table()
    print("  created decision_memory")

    outcomes_repo.create_table()
    print("  created trade_outcomes")

    eval_repo.create_table()
    print("  created eval_results")

    print("All tables created")


if __name__ == "__main__":
    print("=== QuorumNexus DB setup ===")
    print("Enabling pgvector...")
    _enable_pgvector()
    print("Dropping all tables...")
    _drop_all()
    print("Creating all tables...")
    _create_all()
    print("=== Setup complete ===")
