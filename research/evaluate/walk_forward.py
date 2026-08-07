from __future__ import annotations

import pandas as pd

from research.evaluate.forward import ForwardReturns
from research.universe import Universe


class WalkForward:
    def __init__(
        self,
        universe: Universe,
        forward: ForwardReturns,
        benchmark: str = "SPY",
    ) -> None:
        self.universe = universe
        self.forward = forward
        self.benchmark_ticker = benchmark

    def __repr__(self) -> str:
        return (
            f"WalkForward(universe={self.universe!r}, forward={self.forward!r}, "
            f"benchmark={self.benchmark_ticker!r})"
        )

    def run(self, signal_days, population=None) -> pd.DataFrame:
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
            rows.append(
                {
                    "signal_day": pd.Timestamp(day).date(),
                    "n": len(population_frame),
                    "median_return": population_frame.forward_return.median(),
                    "hit_rate": (population_frame.forward_return > 0).mean(),
                    "benchmark_return": benchmark_return,
                    "beat_benchmark_rate": (
                        population_frame.forward_return > benchmark_return
                    ).mean(),
                    "excess_median": population_frame.forward_return.median()
                    - benchmark_return,
                    "complete_pct": population_frame.complete.mean(),
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def summarize(by_date: pd.DataFrame) -> dict:
        if by_date.empty:
            raise ValueError("no dates produced a measurement; nothing to summarize")
        return {
            "dates": len(by_date),
            "median_of_medians": by_date.median_return.median(),
            "median_excess": by_date.excess_median.median(),
            "pct_dates_beat_benchmark": (by_date.excess_median > 0).mean(),
            "median_within_date_hit_rate": by_date.hit_rate.median(),
            "median_complete_pct": by_date.complete_pct.median(),
        }


if __name__ == "__main__":
    SIGNAL_DAYS = pd.date_range("2016-01-01", "2025-01-01", freq="QS").tolist()

    walk = WalkForward(
        Universe(), ForwardReturns(horizon_sessions=252), benchmark="SPY"
    )
    print(f"\n{walk!r}")
    print(
        f"  {len(SIGNAL_DAYS)} quarterly signal days,"
        f" {SIGNAL_DAYS[0].date()} -> {SIGNAL_DAYS[-1].date()}\n"
    )

    by_date = walk.run(SIGNAL_DAYS)
    print(
        by_date.to_string(
            index=False,
            formatters={
                "median_return": "{:+.2%}".format,
                "hit_rate": "{:.1%}".format,
                "benchmark_return": "{:+.2%}".format,
                "beat_benchmark_rate": "{:.1%}".format,
                "excess_median": "{:+.2%}".format,
                "complete_pct": "{:.1%}".format,
            },
        )
    )

    summary = WalkForward.summarize(by_date)
    print("\nSUMMARY ACROSS ALL DATES")
    print(f"  dates                          {summary['dates']}")
    print(f"  median of per-date medians     {summary['median_of_medians']:+.2%}")
    print(f"  median excess vs benchmark     {summary['median_excess']:+.2%}")
    print(f"  dates where median beat bench  {summary['pct_dates_beat_benchmark']:.1%}")
    print(
        f"  median within-date hit rate    {summary['median_within_date_hit_rate']:.1%}"
    )
    print(f"  median pct complete            {summary['median_complete_pct']:.1%}")

    print("\n2019-07-01 IN CONTEXT (nearest quarterly date to forward.py's demo)")
    covid_row = by_date[by_date.signal_day == pd.Timestamp("2019-07-01").date()]
    if not covid_row.empty:
        print(covid_row.to_string(index=False))
        rank = (by_date.excess_median < covid_row.excess_median.iloc[0]).sum()
        print(
            f"  ranked {rank + 1} of {len(by_date)} dates by excess return (1 = worst)"
        )
