"""
QuorumNexus pipeline entrypoint.

Usage:
    uv run python -m set_up.main <command>

Commands:
    setup    Enable pgvector and create all tables
    load     Run the initial full data load
    update   Run the daily incremental update
"""

import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "setup":
        from set_up.setup_db import enable_pgvector, drop_all, create_all

        enable_pgvector()
        drop_all()
        create_all()

    elif cmd == "load":
        from set_up import load_data

        load_data.main()

    elif cmd == "update":
        from set_up import daily_update

        sh = daily_update.SharadarData()
        daily_update.update_equity_prices(sh)
        daily_update.update_fund_prices(sh)
        daily_update.update_indicators()
        daily_update.update_fundamentals(sh)
        daily_update.update_insider(sh)
        daily_update.update_events(sh)
        daily_update.update_macro()
        daily_update.update_tickers(sh)
        daily_update.update_institutional(sh)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
