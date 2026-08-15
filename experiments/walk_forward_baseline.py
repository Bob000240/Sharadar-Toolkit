"""The unfiltered baseline: how does the whole structural universe do?

Every variant in the other experiments is measured against this. Lifted out of
research/evaluate/walk_forward.py, where it lived as a __main__ block.

Run: uv run python -m experiments.walk_forward_baseline
"""

import pandas as pd

import research.calendar as calendar
from research.evaluate.forward import ForwardReturns
from research.evaluate.walk_forward import WalkForward
from research.universe import Universe

# Quarter starts are mostly holidays or weekends; schedule() snaps each onto
# the quarter's opening session so every signal day is one the market held.
SIGNAL_DAYS = calendar.schedule("2016-01-01", "2025-01-01", freq="QS")

walk = WalkForward(Universe(), ForwardReturns(horizon_sessions=252), benchmark="SPY")
print(f"\n{walk!r}")
print(
    f"  {len(SIGNAL_DAYS)} quarterly signal days,"
    f" {SIGNAL_DAYS[0]} -> {SIGNAL_DAYS[-1]}\n"
)

by_date = walk.run(SIGNAL_DAYS)
print(
    by_date.to_string(
        index=False,
        formatters={
            "mean_return": "{:+.2%}".format,
            "hit_rate": "{:.1%}".format,
            "benchmark_return": "{:+.2%}".format,
            "beat_benchmark_rate": "{:.1%}".format,
            "excess_mean": "{:+.2%}".format,
            "complete_pct": "{:.1%}".format,
        },
    )
)

summary = WalkForward.summarize(by_date)
print("\nSUMMARY ACROSS ALL DATES")
print(f"  dates                          {summary['dates']}")
print(f"  median of per-date means       {summary['median_of_means']:+.2%}")
print(f"  median excess vs benchmark     {summary['median_excess']:+.2%}")
print(f"  dates where median beat bench  {summary['pct_dates_beat_benchmark']:.1%}")
print(f"  median within-date hit rate    {summary['median_within_date_hit_rate']:.1%}")
print(f"  median pct complete            {summary['median_complete_pct']:.1%}")

print("\n2019-07-01 IN CONTEXT (nearest quarterly date to forward.py's demo)")
covid_row = by_date[by_date.signal_day == pd.Timestamp("2019-07-01").date()]
if not covid_row.empty:
    print(covid_row.to_string(index=False))
    rank = (by_date.excess_mean < covid_row.excess_mean.iloc[0]).sum()
    print(f"  ranked {rank + 1} of {len(by_date)} dates by excess return (1 = worst)")
