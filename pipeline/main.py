"""
Sharadar Toolkit pipeline entrypoint.

Usage:
    uv run python -m pipeline.main <command>

Commands:
    setup                Create all tables
    load                 Run the initial full data load
    update               Run the daily incremental update
    register <name>      Register/update a strategy from its NAME/DESCRIPTION.
    retire <name>        Soft-retire a strategy (no new entries; row kept for history).

<name> is the strategy name, e.g. sector_leaders (-> research.presets.strat_sector_leaders).
"""

import sys

_STRATEGY_PKG = "research.presets"


def _load_strategy(name: str):
    """Import strategy `name` (research.presets.strat_<name>) and return its
    module. Exits if it lacks NAME/DESCRIPTION."""
    import importlib

    module = importlib.import_module(f"{_STRATEGY_PKG}.strat_{name}")
    if not hasattr(module, "NAME") or not hasattr(module, "DESCRIPTION"):
        sys.exit(f"{name} has no NAME/DESCRIPTION constants")
    return module


def main():
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

    elif cmd == "register":
        if len(sys.argv) < 3:
            sys.exit("usage: register <name>")
        import database.state.strategy_profiles_repository as profiles_repo

        module = _load_strategy(sys.argv[2])
        profiles_repo.upsert_profile(module.NAME, module.DESCRIPTION)
        print(f"registered {module.NAME}")

    elif cmd == "retire":
        if len(sys.argv) < 3:
            sys.exit("usage: retire <name>")
        import database.state.strategy_profiles_repository as profiles_repo

        name = sys.argv[2]
        if profiles_repo.retire_profile(name):
            print(f"retired {name} (row kept in registry; re-register to reactivate)")
        else:
            print(f"no profile named {name}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
