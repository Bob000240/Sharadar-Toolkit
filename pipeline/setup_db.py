"""Create every database table, in dependency order.

Run once before the initial load::

    uv run python -m pipeline.setup_db
"""

from sqlalchemy import text
from database.db_connection import get_connection

import database.source.daily_repo as daily_repo
import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
import database.source.technical_features_repo as technical_features_repo
import database.source.tickers_repo as tickers_repo
import database.source.fundamentals_repo as fundamentals_repo
import database.source.insider_repo as insider_repo
import database.source.institutional_repo as institutional_repo
import database.source.event_repo as event_repo


def drop_all():
    """Drop every table, children before parents.

    Order matters: dependants are dropped first so a CASCADE never has to reach
    across a foreign key that still has rows behind it.
    """
    tables = [
        "events",
        "institutional_ownership",
        "insider_transactions",
        "fundamentals",
        "tickers",
        "technical_features",
        "daily_valuation",
        "fund_prices",
        "equity_prices",
    ]
    with get_connection().begin() as conn:
        for t in tables:
            conn.execute(text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
            print(f"  dropped {t}")
    print("All tables dropped")


def create_all():
    """Create every table in dependency order.

    Idempotent, since each repository creates its table only if absent.
    """
    equity_repo.create_table()
    print("  created equity_prices")
    fund_repo.create_table()
    print("  created fund_prices")
    daily_repo.create_table()
    print("  created daily_valuation")
    technical_features_repo.create_table()
    print("  created technical_features")
    tickers_repo.create_table()
    print("  created tickers")
    fundamentals_repo.create_table()
    print("  created fundamentals")
    insider_repo.create_table()
    print("  created insider_transactions")
    institutional_repo.create_table()
    print("  created institutional_ownership")
    event_repo.create_table()
    print("  created events")

    print("All tables created")


if __name__ == "__main__":
    print("=== Sharadar Toolkit DB setup ===")
    drop_all()
    create_all()
    print("=== Done ===")
