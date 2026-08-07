"""
Creates all DB tables in dependency order.
Run once before load_data.py.

    uv run python -m pipeline.setup_db
"""

from sqlalchemy import text
from database.db_connection import get_connection

import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
import database.source.technical_features_repo as technical_features_repo
import database.source.tickers_repo as tickers_repo
import database.source.fundamentals_repo as fundamentals_repo
import database.source.insider_repo as insider_repo
import database.source.institutional_repo as institutional_repo
import database.source.event_repo as event_repo
import database.source.macro_repo as macro_repo
import database.state.strategy_profiles_repository as profiles_repo


def enable_pgvector():
    with get_connection().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    print("pgvector enabled")


def drop_all():
    tables = [
        "strategy_profiles",
        "events",
        "institutional_holdings",
        "insider_transactions",
        "fundamentals",
        "tickers",
        "technical_features",
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
    equity_repo.create_table()
    print("  created equity_prices")
    fund_repo.create_table()
    print("  created fund_prices")
    technical_features_repo.create_table()
    print("  created technical_features")
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

    profiles_repo.create_table()
    print(
        "  created strategy_profiles (empty; register strategies via pipeline.main register)"
    )

    print("All tables created")


if __name__ == "__main__":
    print("=== QuorumNexus DB setup ===")
    enable_pgvector()
    drop_all()
    create_all()
    print("=== Done ===")
