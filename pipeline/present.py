"""Render a screen result for a terminal and for a file.

Presentation only: what a screen *is* lives in ``research.spec`` and what it
does in ``research.screen``. The terminal view is deliberately narrower than
the export — a reader wants the shortlist and the attrition behind it, while a
file should carry every signal value the run stood on.
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd

from research.screen import ScreenResult

# Returns carry a sign because their direction is the point; rates do not,
# because "+100% complete" reads as a change rather than a level. A pluggable
# metric's median is left alone: an information coefficient is not a percentage.
_SIGNED_COLUMNS = frozenset(
    {
        "mean_return",
        "benchmark_return",
        "excess_mean",
        "median_of_means",
        "median_excess",
    }
)
_RATE_COLUMNS = frozenset(
    {
        "hit_rate",
        "beat_benchmark_rate",
        "complete_pct",
        "pct_dates_beat_benchmark",
        "median_within_date_hit_rate",
        "median_complete_pct",
    }
)

_NO_SIGNIFICANCE = (
    "These are medians over the measured dates. There is no t-statistic, "
    "p-value, or\nconfidence interval behind any of them: a positive median "
    "excess is not evidence\nthat the rule beats the benchmark."
)

_RANKED_COLUMNS = ("ticker", "sector", "score", "rank", "coverage")
_IDENTITY_COLUMNS = ("ticker", "sector")
_TERMINAL_LIMIT = 25

EXPORT_SUFFIXES = (".csv", ".json")


def present(result: ScreenResult, limit: int = _TERMINAL_LIMIT) -> None:
    """Print the run: what was asked, what it cost, and what survived."""
    spec = result.spec
    print(f"\n{spec.name} · as of {result.signal_day}")
    if spec.description:
        print(f"  {spec.description}")
    print(f"  structural universe {result.universe_size:,} -> {len(result):,} selected")

    print("\nFUNNEL")
    print(_funnel(result))

    print("\nSELECTED")
    if not len(result):
        print("  nothing qualified")
        return
    print(_selections(result, limit))
    if len(result) > limit:
        print(f"  ... {len(result) - limit:,} more, export for the full list")


def present_evaluation(
    by_date: pd.DataFrame,
    summaries: pd.DataFrame,
    horizon: int,
    benchmark: str,
) -> None:
    """Print a walk-forward: every measured date, then the medians across them.

    Closes on the absence of significance testing, because a table of excess
    returns reads as evidence and this one is not.
    """
    dates = sorted(by_date["signal_day"].unique())
    print(f"\n{horizon}-session horizon vs {benchmark}")
    print(f"  {len(dates)} dates from {dates[0]} to {dates[-1]}")

    print("\nBY DATE")
    print(_percentages(by_date).to_string(index=False))

    print("\nSUMMARY")
    print(_percentages(summaries).to_string(index=False))
    print(f"\n{_NO_SIGNIFICANCE}")


def export(result: ScreenResult, path: Path) -> Path:
    """Write the result to ``path``, in the format its suffix names.

    CSV carries the selections with every signal value behind them; JSON adds
    the run's own context, so a stored result can be read back without the spec
    that produced it.

    :raises ValueError: for a suffix with no writer, rather than guessing.
    """
    path = Path(path)
    if path.suffix.lower() == ".csv":
        result.frame.to_csv(path, index=False)
    elif path.suffix.lower() == ".json":
        path.write_text(json.dumps(document(result), indent=2, default=_encode))
    else:
        raise ValueError(
            f"cannot export to {path.suffix or 'a file with no suffix'}; "
            f"use one of {', '.join(EXPORT_SUFFIXES)}"
        )
    return path


def export_table(frame: pd.DataFrame, path: Path) -> Path:
    """Write a plain frame to ``path``, in the format its suffix names.

    :raises ValueError: for a suffix with no writer, rather than guessing.
    """
    path = Path(path)
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
    elif path.suffix.lower() == ".json":
        path.write_text(
            json.dumps(frame.to_dict(orient="records"), indent=2, default=_encode)
        )
    else:
        raise ValueError(
            f"cannot export to {path.suffix or 'a file with no suffix'}; "
            f"use one of {', '.join(EXPORT_SUFFIXES)}"
        )
    return path


def _percentages(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with return and rate columns rendered as percentages.

    Formatted into strings rather than through ``to_string`` formatters, so one
    rendering serves both the per-date table and the summary, whose columns are
    named differently.
    """
    shown = frame.copy()
    for column in shown.columns:
        if column in _SIGNED_COLUMNS:
            shown[column] = shown[column].map(_signed)
        elif column in _RATE_COLUMNS:
            shown[column] = shown[column].map(_rate)
    return shown


def _signed(value) -> str:
    """Render a return, where the sign is the point."""
    return "-" if pd.isna(value) else f"{value:+.1%}"


def _rate(value) -> str:
    """Render a rate, which is a level rather than a change."""
    return "-" if pd.isna(value) else f"{value:.0%}"


def document(result: ScreenResult) -> dict:
    """Return the result as a plain dictionary, ready to serialise."""
    return {
        "screen": result.spec.name,
        "description": result.spec.description,
        "signal_day": result.signal_day,
        "universe_size": result.universe_size,
        "selected": len(result),
        "fields": list(result.spec.fields()),
        "funnel": result.funnel.to_dict(orient="records"),
        "selections": result.frame.to_dict(orient="records"),
    }


def _funnel(result: ScreenResult) -> str:
    """Return the attrition table, or a line saying nothing narrowed it."""
    if result.funnel.empty:
        return "  no elective filters; the structural universe stands"
    return result.funnel.to_string(index=False)


def _selections(result: ScreenResult, limit: int) -> str:
    """Return the shortlist, ranked columns first where the spec ranked."""
    columns = _RANKED_COLUMNS if result.spec.rank else _IDENTITY_COLUMNS
    present_columns = [c for c in columns if c in result.frame.columns]
    return result.frame.head(limit)[present_columns].to_string(
        index=False,
        formatters={
            "score": "{:.1f}".format,
            "coverage": "{:.0%}".format,
        },
    )


def _encode(value):
    """Serialise the types a screen frame carries that JSON does not."""
    if isinstance(value, (pd.Timestamp, date)):
        return str(value)
    if isinstance(value, (pd.Series, pd.Index)):
        return list(value)
    if pd.isna(value):
        return None
    return str(value)
