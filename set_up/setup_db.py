"""
Creates all DB tables in dependency order.
Run once before load_data.py.

    uv run python -m set_up.setup_db
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database.db_connection import get_connection

import database.market.equity_repo as equity_repo
import database.market.fund_repo as fund_repo
import database.market.indicators_repo as indicators_repo
import database.market.tickers_repo as tickers_repo
import database.market.fundamentals_repo as fundamentals_repo
import database.market.insider_repo as insider_repo
import database.market.institutional_repo as institutional_repo
import database.market.event_repo as event_repo
import database.market.macro_repo as macro_repo
import database.operational.prefilter_profiles_repository as profiles_repo
import database.operational.screened_candidates_repository as candidates_repo
import database.agent_memory.decision_memory_repository as memory_repo
import database.outcomes.trade_outcomes_repository as outcomes_repo
import database.outcomes.eval_repository as eval_repo


def enable_pgvector():
    with get_connection().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    print("pgvector enabled")


def drop_all():
    tables = [
        "eval_results",
        "trade_outcomes",
        "decision_memory",
        "screened_candidates",
        "prefilter_profiles",
        "events",
        "institutional_holdings",
        "insider_transactions",
        "fundamentals",
        "tickers",
        "indicators",
        "fund_prices",
        "equity_prices",
        "macro",
    ]
    with get_connection().begin() as conn:
        for t in tables:
            conn.execute(text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
            print(f"  dropped {t}")
    print("All tables dropped")


def create_all():
    # Market data
    equity_repo.create_table()
    print("  created equity_prices")
    fund_repo.create_table()
    print("  created fund_prices")
    indicators_repo.create_table()
    print("  created indicators")
    tickers_repo.create_table()
    print("  created tickers")
    fundamentals_repo.create_table()
    print("  created fundamentals")
    insider_repo.create_table()
    print("  created insider_transactions")
    institutional_repo.create_table()
    print("  created institutional_holdings")
    event_repo.create_table()
    print("  created events")
    macro_repo.create_table()
    print("  created macro")

    # Operational
    profiles_repo.create_table()
    print("  created prefilter_profiles")
    candidates_repo.create_table()
    print("  created screened_candidates")

    # Agent memory + outcomes
    memory_repo.create_table()
    print("  created decision_memory")
    outcomes_repo.create_table()
    print("  created trade_outcomes")
    eval_repo.create_table()
    print("  created eval_results")

    print("All tables created")


if __name__ == "__main__":
    print("=== QuorumNexus DB setup ===")
    enable_pgvector()
    drop_all()
    create_all()
    print("=== Done ===")
