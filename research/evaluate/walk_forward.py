"""Measure one or many populations across a series of signal days.

Each date is independent: a population is rebuilt, measured over the forward
horizon, and compared against a buy-and-hold benchmark over the identical
window. There is no portfolio carried between dates, so this answers whether a
selection rule identifies securities that go on to outperform, not what an
account holding them would have earned.

Summaries are medians across dates rather than means, because a handful of
horizons dominate any nine-year sample and the question is whether a rule works
typically, not what one crisis window did to the average.
"""

from __future__ import annotations

import pandas as pd

from research.evaluate.forward import ForwardReturns
from research.universe import Universe


class WalkForward:
    """A per-date measurement harness for one or many populations.

    Public methods are ``run``, for a single population, ``compare``, for many
    at once, and the static ``summarize``. Instance variables are ``universe``,
    ``forward``, and ``benchmark_ticker``.
    """

    def __init__(
        self,
        universe: Universe,
        forward: ForwardReturns,
        benchmark: str = "SPY",
    ) -> None:
        """Compose a universe, a forward-return measure, and a benchmark.

        ``benchmark`` is a fund ticker read from the fund price table, not an
        equity.
        """
        self.universe = universe
        self.forward = forward
        self.benchmark_ticker = benchmark

    def __repr__(self) -> str:
        """Return the universe, horizon, and benchmark in use."""
        return (
            f"WalkForward(universe={self.universe!r}, forward={self.forward!r}, "
            f"benchmark={self.benchmark_ticker!r})"
        )

    def run(self, signal_days, population=None) -> pd.DataFrame:
        """Return one row per signal day for a single population.

        ``population`` is a callable taking a signal day and returning the
        tickers to measure; omitting it measures the whole structural universe.

        ``measured`` counts the securities that both entered the population and
        produced a forward return, not the number the population selected. The
        two differ when a name has no subsequent price data at all, which is
        rare mid-sample and common at the end, where the horizon runs past the
        data. Names that delist mid-horizon are measured rather than dropped and
        are counted again in ``complete_pct``; excluding them would bias every
        result upward.

        Dates where the population or the benchmark cannot be measured are
        skipped rather than reported as zero.
        """
        rows = []
        for day in signal_days:
            tickers = population(day) if population else self.universe.run(day).ticker
            population_frame = self.forward.run(tickers, day)
            if population_frame.empty:
                continue
            bench = self.forward.benchmark([self.benchmark_ticker], day)
            if bench.empty:
                continue
            benchmark_return = bench.forward_return.iloc[0]
            mean_return = population_frame.forward_return.mean()
            rows.append(
                {
                    "signal_day": pd.Timestamp(day).date(),
                    "measured": len(population_frame),
                    "mean_return": mean_return,
                    "hit_rate": (population_frame.forward_return > 0).mean(),
                    "benchmark_return": benchmark_return,
                    "beat_benchmark_rate": (
                        population_frame.forward_return > benchmark_return
                    ).mean(),
                    "excess_mean": mean_return - benchmark_return,
                    "complete_pct": population_frame.complete.mean(),
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def summarize(by_date: pd.DataFrame) -> dict:
        """Reduce a per-date frame to one summary across all of its dates.

        Medians rather than means throughout, so one extreme horizon cannot
        carry the result. ``pct_dates_beat_benchmark`` is the exception: a
        fraction of dates rather than a median.

        Raise ValueError when no date produced a measurement.
        """
        if by_date.empty:
            raise ValueError("no dates produced a measurement; nothing to summarize")
        return {
            "dates": len(by_date),
            "median_of_means": by_date.mean_return.median(),
            "median_excess": by_date.excess_mean.median(),
            "pct_dates_beat_benchmark": (by_date.excess_mean > 0).mean(),
            "median_within_date_hit_rate": by_date.hit_rate.median(),
            "median_complete_pct": by_date.complete_pct.median(),
        }

    def compare(self, signal_days, filters, additions=None) -> pd.DataFrame:
        """Return one row per (variant, signal day) for many populations.

        ``filters`` maps a label to anything exposing ``apply(frame)``, or to
        None for the unfiltered baseline. ``additions`` is an optional callable
        taking the frame and the day, used to attach signal facts before the
        variants run.

        Same columns as ``run``, including ``measured``; see its docstring for
        what that counts. Dates loop outside and variants inside, so the
        universe query and the forward returns are computed once per date and
        merely reindexed per variant. That is what makes a many-variant sweep
        affordable, and each variant applies to the same untouched frame, so
        nothing accumulates between them.
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

            for label, condition in filters.items():
                selected = frame if condition is None else condition.apply(frame)
                returns = by_ticker.reindex(selected["ticker"]).dropna(
                    subset=["forward_return"]
                )
                if returns.empty:
                    continue
                mean_return = returns.forward_return.mean()
                rows.append(
                    {
                        "variant": label,
                        "signal_day": pd.Timestamp(day).date(),
                        "measured": len(returns),
                        "mean_return": mean_return,
                        "hit_rate": (returns.forward_return > 0).mean(),
                        "benchmark_return": benchmark_return,
                        "beat_benchmark_rate": (
                            returns.forward_return > benchmark_return
                        ).mean(),
                        "excess_mean": mean_return - benchmark_return,
                        "complete_pct": returns.complete.mean(),
                    }
                )
        return pd.DataFrame(rows)
