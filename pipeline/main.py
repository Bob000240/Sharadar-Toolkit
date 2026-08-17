"""
Sharadar Toolkit pipeline entrypoint.

Usage:
    uv run python -m pipeline.main <command>

Commands:
    setup                Create all tables
    load                 Run the initial full data load
    update               Run the daily incremental update
"""

import sys


def main():
    """Dispatch one subcommand from ``sys.argv``.

    Each command imports its dependencies lazily, so an unrelated broken import
    cannot stop the others from running. The update command keeps going after a
    failed step and exits non-zero at the end with the list of failures, because a
    single unavailable vendor endpoint should not abandon the rest of the load.
    """
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "setup":
        from pipeline.setup_db import drop_all, create_all

        drop_all()
        create_all()

    elif cmd == "load":
        from pipeline import load_data

        load_data.main()

    elif cmd == "update":
        from pipeline import daily_update

        sh = daily_update.SharadarData()
        steps = [
            ("Equity prices", lambda: daily_update.update_equity_prices(sh)),
            ("Fund prices", lambda: daily_update.update_fund_prices(sh)),
            ("Technical features", daily_update.update_technical_features),
            ("Fundamentals", lambda: daily_update.update_fundamentals(sh)),
            ("Insider", lambda: daily_update.update_insider(sh)),
            ("Events", lambda: daily_update.update_events(sh)),
            ("Tickers", lambda: daily_update.update_tickers(sh)),
            ("Institutional", lambda: daily_update.update_institutional(sh)),
        ]
        failed = []
        for label, step in steps:
            try:
                step()
            except Exception as exc:
                failed.append(label)
                print(f"{label}: FAILED — {type(exc).__name__}: {exc}")

        if failed:
            print(
                f"\n=== {len(failed)}/{len(steps)} step(s) failed: "
                f"{', '.join(failed)} ==="
            )
            sys.exit(1)
        print(f"\n=== all {len(steps)} steps completed ===")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
