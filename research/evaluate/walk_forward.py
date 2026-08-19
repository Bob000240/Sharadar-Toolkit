"""Measure one or many populations across a series of signal days.

Each date is independent: a population is rebuilt, measured over the forward
horizon, and compared against a buy-and-hold benchmark over the same window.
No portfolio is carried between dates, so this answers whether a selection rule
picks securities that outperform, not what an account holding them earned.

Summaries are medians across dates, since a handful of horizons dominate any
nine-year sample. ``metrics`` adds statistics beyond the six §6.9 requires; the
six are always present and cannot be replaced. A population selected by a
``Ranking`` carries its ``score`` through, which is what lets a metric ask
whether the ranking ordered the returns.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from research.evaluate.forward import ForwardReturns
from research.evaluate.metrics import EvalContext, EvalMetric
from research.universe import Universe

#: Columns every per-date row carries, whatever metrics were requested. A
#: custom metric may not take one of these names, since it would overwrite a
#: figure the specification requires.
BASELINE_COLUMNS = (
    "signal_day",
    "measured",
    "mean_return",
    "hit_rate",
    "benchmark_return",
    "beat_benchmark_rate",
    "excess_mean",
    "complete_pct",
)

_VARIANT_COLUMN = "variant"


#: Columns carried from the selection onto the measured frame when present.
#: ``score`` is what rank-quality metrics correlate against and ``sector`` what
#: the concentration metric counts; everything else a signal frame holds is
#: left behind, since a metric that needed it would be describing the selection
#: rather than its outcome.
CARRIED_COLUMNS = ("score", "sector")


def _selection(selected) -> tuple[object, pd.DataFrame | None]:
    """Split a population result into its tickers and any carried columns.

    Accepts bare tickers or a ``Ranking``'s frame, so score- and sector-based
    metrics work without forcing every caller to return a frame.
    """
    if not isinstance(selected, pd.DataFrame):
        return selected, None
    carried = [c for c in CARRIED_COLUMNS if c in selected.columns]
    if not carried:
        return selected["ticker"], None
    return selected["ticker"], selected.set_index("ticker")[carried]


def _slice_panel(panel: pd.DataFrame | None, tickers) -> pd.DataFrame | None:
    """Narrow a date's shared panel to the securities one variant selected.

    None rather than an empty frame, so a metric special-cases one case only.
    """
    if panel is None or panel.empty:
        return None
    held = [ticker for ticker in tickers if ticker in panel.columns]
    return panel[held] if held else None


class WalkForward:
    """A per-date measurement harness for one or many populations."""

    def __init__(
        self,
        universe: Universe,
        forward: ForwardReturns,
        benchmark: str = "SPY",
        metrics: Iterable[EvalMetric] = (),
    ) -> None:
        """Compose a universe, a forward-return measure, a benchmark, and metrics.

        ``benchmark`` is a fund ticker, not an equity.

        :raises ValueError: when a metric shadows a baseline column or two
            share a name, either of which silently drops a report column.
        """
        self.universe = universe
        self.forward = forward
        self.benchmark_ticker = benchmark
        self.metrics = tuple(metrics)

        names = [metric.name for metric in self.metrics]
        reserved = sorted(set(names) & {*BASELINE_COLUMNS, _VARIANT_COLUMN})
        if reserved:
            raise ValueError(f"metric names are reserved report columns: {reserved}")
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"metric names appear more than once: {duplicates}")

    def __repr__(self) -> str:
        """Return the universe, horizon, benchmark, and any extra metrics."""
        extra = ", ".join(metric.name for metric in self.metrics)
        return (
            f"WalkForward(universe={self.universe!r}, forward={self.forward!r}, "
            f"benchmark={self.benchmark_ticker!r}, metrics=({extra}))"
        )

    @property
    def needs_panel(self) -> bool:
        """Whether any metric reads the panel, which is what makes it fetched."""
        return any(metric.needs_panel for metric in self.metrics)

    def _row(
        self,
        measured: pd.DataFrame,
        benchmark_return: float,
        day,
        panel: pd.DataFrame | None = None,
    ) -> dict:
        """Build one date's report row: the baseline six, then every metric.

        Metrics apply last and cannot collide with a baseline name, so a custom
        statistic never displaces a figure §6.9 requires.
        """
        mean_return = measured.forward_return.mean()
        row = {
            "signal_day": pd.Timestamp(day).date(),
            "measured": len(measured),
            "mean_return": mean_return,
            "hit_rate": (measured.forward_return > 0).mean(),
            "benchmark_return": benchmark_return,
            "beat_benchmark_rate": (measured.forward_return > benchmark_return).mean(),
            "excess_mean": mean_return - benchmark_return,
            "complete_pct": measured.complete.mean(),
        }
        context = EvalContext(
            measured=measured, benchmark_return=benchmark_return, panel=panel
        )
        for metric in self.metrics:
            row[metric.name] = metric.fn(context)
        return row

    def run(self, signal_days, population=None) -> pd.DataFrame:
        """Return one row per signal day for a single population.

        ``population`` takes a signal day and returns tickers, or a ``Ranking``
        frame to enable the rank-quality metrics; omitting it measures the
        whole structural universe.

        :returns: one row per measurable date. ``measured`` counts securities
            that produced a forward return, not those selected. Names delisting
            mid-horizon are measured, not dropped — excluding them would bias
            every result upward. Unmeasurable dates are skipped, not zeroed.
        """
        rows = []
        for day in signal_days:
            selected = population(day) if population else self.universe.run(day).ticker
            tickers, carried = _selection(selected)
            population_frame = self.forward.run(tickers, day)
            if population_frame.empty:
                continue
            bench = self.forward.benchmark([self.benchmark_ticker], day)
            if bench.empty:
                continue
            if carried is not None:
                population_frame = population_frame.join(
                    carried, on="ticker", how="left"
                )
            panel = (
                self.forward.panel(population_frame["ticker"], day)
                if self.needs_panel
                else None
            )
            rows.append(
                self._row(
                    population_frame, bench.forward_return.iloc[0], day, panel=panel
                )
            )
        return pd.DataFrame(rows)

    @staticmethod
    def summarize(by_date: pd.DataFrame) -> dict:
        """Reduce a per-date frame to one summary across all of its dates.

        Medians throughout so one extreme horizon cannot carry the result;
        ``pct_dates_beat_benchmark`` is the exception. Non-baseline numeric
        columns are summarised as ``median_{name}``.

        :raises ValueError: when no date produced a measurement.
        """
        if by_date.empty:
            raise ValueError("no dates produced a measurement; nothing to summarize")
        summary = {
            "dates": len(by_date),
            "median_of_means": by_date.mean_return.median(),
            "median_excess": by_date.excess_mean.median(),
            "pct_dates_beat_benchmark": (by_date.excess_mean > 0).mean(),
            "median_within_date_hit_rate": by_date.hit_rate.median(),
            "median_complete_pct": by_date.complete_pct.median(),
        }
        known = {*BASELINE_COLUMNS, _VARIANT_COLUMN}
        for column in by_date.columns:
            if column not in known and pd.api.types.is_numeric_dtype(by_date[column]):
                summary[f"median_{column}"] = by_date[column].median()
        return summary

    def compare(self, signal_days, filters, additions=None) -> pd.DataFrame:
        """Return one row per (variant, signal day) for many populations.

        ``filters`` maps a label to anything exposing ``apply(frame)``, or None
        for the unfiltered baseline; a variant returning a ``score`` column
        gets rank-quality metrics. ``additions`` attaches signal facts to the
        frame before the variants run.

        Dates loop outside and variants inside, so the universe query, forward
        returns, and panel are computed once per date and reindexed per
        variant. Each variant sees the same untouched frame.
        """
        rows = []
        for day in signal_days:
            frame = self.universe.run(day)
            if additions is not None:
                frame = additions(frame, day)
            if frame.empty:
                continue

            measured = self.forward.run(frame.ticker, day)
            bench = self.forward.benchmark([self.benchmark_ticker], day)
            if measured.empty or bench.empty:
                continue
            benchmark_return = bench.forward_return.iloc[0]
            by_ticker = measured.set_index("ticker")
            day_panel = (
                self.forward.panel(frame.ticker, day) if self.needs_panel else None
            )

            for label, condition in filters.items():
                selected = frame if condition is None else condition.apply(frame)
                tickers, carried = _selection(selected)
                returns = by_ticker.reindex(tickers).dropna(subset=["forward_return"])
                if returns.empty:
                    continue
                if carried is not None:
                    returns = returns.join(carried, how="left")
                rows.append(
                    {
                        _VARIANT_COLUMN: label,
                        **self._row(
                            returns,
                            benchmark_return,
                            day,
                            panel=_slice_panel(day_panel, returns.index),
                        ),
                    }
                )
        return pd.DataFrame(rows)
