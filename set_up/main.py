import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


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
        sh = load_data.SharadarData()
        # load_data.load_tickers(sh)
        # load_data.load_equity_prices(sh)
        # load_data.load_fund_prices(sh)
        # load_data.load_indicators()
        # load_data.load_fundamentals(sh)
        # load_data.load_insider(sh)
        load_data.load_institutional(sh)
        # load_data.load_events(sh)
        # load_data.load_macro()

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
