"""Sharadar Toolkit pipeline entrypoint.

Usage::

    uv run python -m pipeline.main setup  [dataset]
    uv run python -m pipeline.main load   [dataset]
    uv run python -m pipeline.main update [dataset]
    uv run python -m pipeline.main screen   <name> [--as-of DATE] [--out FILE]
    uv run python -m pipeline.main evaluate <name>... [--from DATE] [--to DATE]

``setup`` recreates tables, ``load`` runs the bulk load, ``update`` runs the
incremental one; each acts on everything unless a dataset narrows it. The
Sharadar code is accepted in place of a dataset name, so ``load SF3A`` and
``load institutional`` are the same request.

``screen`` runs a named screen from ``strategy.toml`` as of a date, printing
the session it resolved to, the funnel, and the selections. ``evaluate`` walks
one or more of them forward through history::

    uv run python -m pipeline.main evaluate quality_at_a_price deep_value
"""

import argparse
import sys
from pathlib import Path

from pipeline import datasets, report
from pipeline.datasets import DATASETS

# Step order for `update`. Technical features run last because they are derived
# from equity prices rather than fetched, so they should recompute after every
# vendor step has landed whatever it is going to land.
UPDATE_STEPS = (
    ("equity", "update_equity_prices", True),
    ("fund", "update_fund_prices", True),
    ("fundamentals", "update_fundamentals", True),
    ("daily", "update_daily_valuation", True),
    ("insider", "update_insider", True),
    ("events", "update_events", True),
    ("tickers", "update_tickers", True),
    ("institutional", "update_institutional", False),
    ("technicals", "update_technical_features", False),
)
"""Ordered update steps: dataset, function, whether it takes the vendor client.

The last flag is declared rather than inspected. Steps needing no client still
take arguments of their own — ``update_technical_features`` has a batch size —
so "has parameters" is not the same question as "wants the client".
"""

_UPDATE_ACTIONS = {
    "institutional": "re-exporting recent quarters",
    "technicals": "recomputing from equity prices",
}


def resolve(dataset: str) -> str:
    """Return the canonical dataset name for a name or a Sharadar code.

    :raises SystemExit: on an unknown name, since a typo would otherwise fall
        through to running the whole pipeline.
    """
    name = datasets.resolve(dataset)
    if name is None:
        sys.exit(f"Unknown dataset: {dataset}\nValid datasets: {', '.join(DATASETS)}")
    return name


def run_setup(dataset: str | None) -> None:
    """Recreate every table, or just one dataset's.

    Destructive either way: the drop lands whether or not a reload follows.
    """
    if dataset is None:
        from pipeline.setup_db import create_all, drop_all

        drop_all()
        create_all()
        return
    repo = datasets.repo(dataset)
    repo.drop_table()
    repo.create_table()
    print(f"recreated {dataset}")


def run_load(dataset: str | None) -> None:
    """Bulk-load every dataset, or just one.

    Exits non-zero if any dataset failed, having attempted the rest.
    """
    from pipeline import load_data

    if dataset is None:
        if load_data.main():
            sys.exit(1)
        return

    run = report.Run(
        "load",
        datasets.label(dataset),
        f"{load_data.START_DATE} → {load_data.END_DATE}",
    )
    code = datasets.code(dataset)
    action = (
        "computing from equity prices" if code is None else f"exporting SHARADAR/{code}"
    )
    with run.step(datasets.label(dataset), action) as result:
        result.rows = (
            load_data.load_technical_features()
            if code is None
            else load_data.load_sharadar_table(code)
        )
    if run.finish():
        sys.exit(1)


def run_update(dataset: str | None) -> None:
    """Run every update step, or just one.

    A failed step is reported and the rest still run, because one unavailable
    vendor endpoint should not abandon the others. Exits non-zero with the list.
    """
    from pipeline import daily_update

    sh = daily_update.SharadarData()
    selected = [step for step in UPDATE_STEPS if dataset is None or step[0] == dataset]
    scope = "all datasets" if dataset is None else datasets.label(dataset)
    run = report.Run("update", scope, daily_update.TODAY)

    for name, function_name, needs_client in selected:
        step = getattr(daily_update, function_name)
        action = _UPDATE_ACTIONS.get(name, "fetching")
        with run.step(datasets.label(name), action) as result:
            outcome = step(sh) if needs_client else step()
            if outcome is not None:
                result.rows, result.note = outcome.rows, outcome.note
                result.detail = outcome.detail

    if run.finish():
        sys.exit(1)


def run_screen(name: str, as_of: str | None, out: str | None) -> None:
    """Run one named screen and present it, exporting when asked.

    Validation happens before any query: an unknown screen, an unregistered
    field, or a date the loaded calendar cannot cover should cost nothing.
    """
    import research.calendar as calendar
    import research.screen as screen
    import research.spec as spec_module
    from pipeline import present

    spec = _screen_spec(spec_module.catalog(), name)
    _check_export_suffix(out)

    try:
        signal_day = calendar.align(as_of) if as_of else calendar.latest_session()
    except ValueError as exc:
        sys.exit(str(exc))

    result = screen.run(spec, signal_day)
    present.present(result)
    if out is not None:
        print(f"\nwrote {present.export(result, Path(out))}")


def run_evaluate(
    names: list[str],
    start: str | None,
    end: str | None,
    horizon: int,
    every: str,
    out: str | None,
) -> None:
    """Walk one or more screens forward through history and report each date.

    Every screen is rebuilt independently on every date under the same
    point-in-time rules, so this measures whether a selection *rule* picks
    securities that outperform — not what an account holding them earned.
    """
    import pandas as pd

    import research.calendar as calendar
    import research.screen as screen
    import research.spec as spec_module
    from pipeline import present
    from research.evaluate.forward import ForwardReturns
    from research.evaluate.walk_forward import WalkForward

    catalog = spec_module.catalog()
    specs = [_screen_spec(catalog, name) for name in names]
    _check_export_suffix(out)

    last = calendar.last_session()
    try:
        signal_days = calendar.schedule(
            start or pd.Timestamp(last) - pd.DateOffset(years=5),
            end or last,
            freq=every,
        )
    except ValueError as exc:
        sys.exit(str(exc))
    if not signal_days:
        sys.exit(f"No sessions between {start} and {end} on frequency {every!r}")

    forward = ForwardReturns(horizon)
    run = report.Run("evaluate", ", ".join(names), f"{len(signal_days)} dates")
    frames, summaries = [], []

    for spec in specs:
        walk = WalkForward(spec.universe, forward)
        with run.step(spec.name, f"measuring {len(signal_days)} dates") as result:
            by_date = walk.run(
                signal_days, lambda day, spec=spec: screen.run(spec, day).frame
            )
            if by_date.empty:
                raise RuntimeError("no date produced a measurement")
            by_date.insert(0, "screen", spec.name)
            frames.append(by_date)
            summaries.append({"screen": spec.name, **walk.summarize(by_date)})
            result.note = f"({len(by_date)} dates measured)"

    if run.finish():
        sys.exit(1)

    by_date = pd.concat(frames, ignore_index=True)
    present.present_evaluation(
        by_date, pd.DataFrame(summaries), horizon, walk.benchmark_ticker
    )
    if out is not None:
        print(f"\nwrote {present.export_table(by_date, Path(out))}")


def _screen_spec(catalog: dict, name: str):
    """Return the named spec, exiting with what is available if it is unknown."""
    if name not in catalog:
        sys.exit(f"Unknown screen: {name}\nAvailable: {', '.join(catalog)}")
    import research.spec as spec_module

    problems = spec_module.validate(catalog[name])
    if problems:
        sys.exit(f"Screen {name!r} is invalid:\n  " + "\n  ".join(problems))
    return catalog[name]


def _check_export_suffix(out: str | None) -> None:
    """Refuse an unwritable ``--out`` before the run rather than after it."""
    from pipeline import present

    if out is not None and Path(out).suffix.lower() not in present.EXPORT_SUFFIXES:
        sys.exit(
            f"Cannot export to {Path(out).suffix or 'a file with no suffix'}; "
            f"use one of {', '.join(present.EXPORT_SUFFIXES)}"
        )


def _parser() -> argparse.ArgumentParser:
    """Build the argument parser, one subcommand per pipeline command."""
    parser = argparse.ArgumentParser(
        prog="pipeline.main",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("setup", "drop and recreate tables"),
        ("load", "bulk-load from the vendor"),
        ("update", "fetch what changed since the last run"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument(
            "dataset",
            nargs="?",
            help=f"one of: {', '.join(DATASETS)} (default: all)",
        )

    screen = commands.add_parser("screen", help="run a named screen")
    screen.add_argument("name", help="a screen defined in strategy.toml")
    screen.add_argument(
        "--as-of",
        metavar="DATE",
        help="resolve to the latest session on or before this date "
        "(default: the newest loaded session)",
    )
    screen.add_argument(
        "--out",
        metavar="FILE",
        help=f"write the result to a file ({' or '.join(present_suffixes())})",
    )

    evaluate = commands.add_parser(
        "evaluate", help="walk a screen forward through history"
    )
    evaluate.add_argument("name", nargs="+", help="one or more screens to compare")
    evaluate.add_argument("--from", dest="start", metavar="DATE", help="first date")
    evaluate.add_argument("--to", dest="end", metavar="DATE", help="last date")
    evaluate.add_argument(
        "--horizon",
        type=int,
        default=63,
        metavar="N",
        help="forward return horizon in sessions (default: 63, about a quarter)",
    )
    evaluate.add_argument(
        "--every",
        default="QS",
        metavar="FREQ",
        help="pandas frequency for the measurement dates (default: QS)",
    )
    evaluate.add_argument(
        "--out",
        metavar="FILE",
        help=f"write the per-date rows to a file ({' or '.join(present_suffixes())})",
    )
    return parser


def present_suffixes() -> tuple[str, ...]:
    """Return the export suffixes, imported late to keep startup cheap."""
    from pipeline import present

    return present.EXPORT_SUFFIXES


def main():
    """Parse the command line and dispatch one command.

    Each command imports its dependencies lazily, so an unrelated broken import
    cannot stop the others from running.
    """
    args = _parser().parse_args()

    if args.command == "screen":
        run_screen(args.name, args.as_of, args.out)
        return

    if args.command == "evaluate":
        run_evaluate(
            args.name, args.start, args.end, args.horizon, args.every, args.out
        )
        return

    dataset = resolve(args.dataset) if args.dataset else None
    {"setup": run_setup, "load": run_load, "update": run_update}[args.command](dataset)


if __name__ == "__main__":
    main()
