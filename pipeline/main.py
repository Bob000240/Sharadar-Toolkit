"""Sharadar Toolkit pipeline entrypoint.

Usage::

    uv run python -m pipeline.main <command> [dataset]

Commands: ``setup`` recreates tables, ``load`` runs the full bulk load,
``update`` runs the incremental update. Each acts on everything unless a
dataset narrows it::

    uv run python -m pipeline.main update institutional
    uv run python -m pipeline.main load fund

Datasets: equity, fund, fundamentals, insider, institutional, events, daily,
tickers, technicals. The Sharadar code is accepted too, so ``load SF3A`` and
``load institutional`` are the same request.
"""

import importlib
import sys

DATASETS = {
    "equity": ("SEP", "equity_repo"),
    "fund": ("SFP", "fund_repo"),
    "fundamentals": ("SF1", "fundamentals_repo"),
    "insider": ("SF2", "insider_repo"),
    "institutional": ("SF3A", "institutional_repo"),
    "events": ("EVENTS", "event_repo"),
    "daily": ("DAILY", "daily_repo"),
    "tickers": ("TICKERS", "tickers_repo"),
    "technicals": (None, "technical_features_repo"),
}
_BY_CODE = {code: name for name, (code, _) in DATASETS.items() if code}

UPDATE_STEPS = (
    ("equity", "Equity prices", "update_equity_prices", True),
    ("fund", "Fund prices", "update_fund_prices", True),
    ("technicals", "Technical features", "update_technical_features", False),
    ("fundamentals", "Fundamentals", "update_fundamentals", True),
    ("daily", "Daily valuation", "update_daily_valuation", True),
    ("insider", "Insider", "update_insider", True),
    ("events", "Events", "update_events", True),
    ("tickers", "Tickers", "update_tickers", True),
    ("institutional", "Institutional ownership", "update_institutional", False),
)
"""Ordered update steps: dataset, label, function, whether it takes the client.

The last flag is declared rather than inspected. Steps that need no client still
take arguments of their own — ``update_technical_features`` has a batch size —
so "has parameters" is not the same question as "wants the vendor client".
"""


def resolve(dataset: str) -> str:
    """Return the canonical dataset name for a name or a Sharadar code.

    :raises SystemExit: on an unknown name, since a typo would otherwise fall
        through to running the whole pipeline.
    """
    key = dataset.lower()
    if key in DATASETS:
        return key
    if dataset.upper() in _BY_CODE:
        return _BY_CODE[dataset.upper()]
    sys.exit(f"Unknown dataset: {dataset}\nValid datasets: {', '.join(DATASETS)}")


def _repo(dataset: str):
    """Import and return the repository module backing one dataset."""
    return importlib.import_module(f"database.source.{DATASETS[dataset][1]}")


def run_setup(dataset: str | None) -> None:
    """Recreate every table, or just one dataset's.

    Destructive either way: the drop lands whether or not a reload follows.
    """
    if dataset is None:
        from pipeline.setup_db import create_all, drop_all

        drop_all()
        create_all()
        return
    repo = _repo(dataset)
    repo.drop_table()
    repo.create_table()
    print(f"recreated {dataset}")


def run_load(dataset: str | None) -> None:
    """Bulk-load every dataset, or just one."""
    from pipeline import load_data

    if dataset is None:
        load_data.main()
        return
    code = DATASETS[dataset][0]
    if code is None:
        load_data.load_technical_features()
        return
    load_data.load_sharadar_table(code)


def run_update(dataset: str | None) -> None:
    """Run every update step, or just one.

    A failed step is reported and the rest still run, because one unavailable
    vendor endpoint should not abandon the others. Exits non-zero with the list.
    """
    from pipeline import daily_update

    sh = daily_update.SharadarData()
    selected = [step for step in UPDATE_STEPS if dataset is None or step[0] == dataset]

    failed = []
    for _, label, function_name, needs_client in selected:
        step = getattr(daily_update, function_name)
        try:
            step(sh) if needs_client else step()
        except Exception as exc:
            failed.append(label)
            print(f"{label}: FAILED — {type(exc).__name__}: {exc}")

    if failed:
        print(
            f"\n=== {len(failed)}/{len(selected)} step(s) failed: "
            f"{', '.join(failed)} ==="
        )
        sys.exit(1)
    print(f"\n=== all {len(selected)} step(s) completed ===")


COMMANDS = {"setup": run_setup, "load": run_load, "update": run_update}


def main():
    """Dispatch ``<command> [dataset]`` from ``sys.argv``.

    Each command imports its dependencies lazily, so an unrelated broken import
    cannot stop the others from running.
    """
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

    dataset = resolve(sys.argv[2]) if len(sys.argv) > 2 else None
    COMMANDS[cmd](dataset)


if __name__ == "__main__":
    main()
