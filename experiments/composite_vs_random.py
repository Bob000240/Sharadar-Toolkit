"""Test whether weighted composites beat a random cut at equal concentration.

::

    uv run python -m experiments.composite_vs_random

Five composites, each cut to the same ``top_n`` from the same prefiltered
population, run against a seeded random selection of that size. The random
control is the whole point: without it a composite that merely inherits the
prefilter's edge, or the mechanical effect of holding fewer names, looks
skillful.

That control exists because of a prior result. The roic/fcf_yield/accruals blend
carried no information at all: its top 200 and its bottom 200 both landed about
2.3pp below the filtered baseline, so the cut was measuring concentration rather
than quality. Every variant therefore holds the same prefilter and the same
``top_n``, and the bar a composite must clear is the random cut, not the
baseline.

The composites and where they come from:

  momentum          twelve-month winners (Jegadeesh & Titman), proximity to the
                    52-week high (George & Hwang), and the volatility-scaled
                    variant of the same idea. ``pct_from_52w_high`` lives in
                    [-1, 0], so "high" means near the high.
  value             cheapness. The prefilter requires positive net income, so
                    "low pe" ranks cheap earners rather than crowning
                    loss-makers cheapest.
  shareholder_yield net payout — dividends plus buybacks less issuance — which
                    carries more information than dividend yield alone
                    (Boudoukh et al.); a shrinking share count is the five-year
                    version of the same statement.
  low_volatility    the low-volatility anomaly (Ang et al.) plus earnings
                    stability. Uses ``interest_coverage`` rather than ``de``,
                    whose negative-equity values would rank distress as least
                    levered.
  profit_growth     gross profitability (Novy-Marx) with top-line and operating
                    growth.

Lifted out of ``research/ranking.py``, where it was a __main__ block.
"""

import pandas as pd

import research.calendar as calendar
from research.evaluate.forward import ForwardReturns
from research.evaluate.walk_forward import WalkForward
from research.filters import Filters, attach_signals
from research.ranking import Ranking
from research.universe import Universe

SIGNAL_DAY = "2024-06-14"
universe = Universe()
frame = attach_signals(universe.run(SIGNAL_DAY), SIGNAL_DAY)

quality = Filters(("marketcap", ">=", 1e9), ("netinccmnusd", ">", 0))
qualified = quality.apply(frame)
print(f"\nuniverse {len(frame):,} -> qualified {len(qualified):,}")

ranking = Ranking(
    ("roic", "high", 0.4),
    ("fcf_yield", "high", 0.3),
    ("accruals", "low", 0.3),
)
print(f"\n{ranking!r}")
ranked = ranking.apply(qualified)
print(f"  scored {len(ranked):,} of {len(qualified):,}")
print(
    ranked.head(10)[
        [
            "ticker",
            "name",
            "score",
            "coverage",
            "roic_pct",
            "fcf_yield_pct",
            "accruals_pct",
        ]
    ].to_string(index=False)
)

print("\nCOVERAGE (share of requested weight actually present)")
print(ranked["coverage"].value_counts().sort_index(ascending=False).head().to_string())

per_industry = Ranking(
    ("roic", "high", 0.4),
    ("fcf_yield", "high", 0.3),
    ("accruals", "low", 0.3),
    group_by="famaindustry",
    top_n=3,
).apply(qualified)
print(f"\nTOP 3 PER INDUSTRY -> {len(per_industry):,} names")
print(
    per_industry.head(9)[["ticker", "famaindustry", "score", "rank"]].to_string(
        index=False
    )
)


class _Chain:
    """Apply ``.apply(frame)`` steps in order as one object.

    Lets ``walk.compare`` treat a filter-then-rank variant as a single unit.

    Local to this experiment on purpose: composing a *spec* is the
    orchestrator's job and happens at the screen level, across universe,
    signals, score, filter, and cut. This composes two frame transforms for a
    comparison sweep, which is a smaller and different thing.
    """

    def __init__(self, *steps) -> None:
        self.steps = steps

    def __repr__(self) -> str:
        return f"_Chain({', '.join(repr(step) for step in self.steps)})"

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        for step in self.steps:
            frame = step.apply(frame)
        return frame


class _RandomCut:
    """Select an arbitrary fixed-size subset, seeded for reproducibility.

    Deterministic across reruns because the seed is fixed, but different per
    date because each date hands it a different frame. Vary the seed to build a
    null distribution rather than a single control path.
    """

    def __init__(self, n: int, seed: int = 0) -> None:
        self.n, self.seed = n, seed

    def __repr__(self) -> str:
        return f"_RandomCut(n={self.n})"

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.sample(n=min(self.n, len(frame)), random_state=self.seed)


TOP_N = 200
COMPOSITES = {
    "momentum": Ranking(
        ("vol_adjusted_momentum", "high", 0.4),
        ("return_252d", "high", 0.3),
        ("pct_from_52w_high", "high", 0.3),
        top_n=TOP_N,
    ),
    "value": Ranking(
        ("fcf_yield", "high", 0.4),
        ("pe", "low", 0.3),
        ("ps", "low", 0.3),
        top_n=TOP_N,
    ),
    "shareholder_yield": Ranking(
        ("net_payout_yield", "high", 0.5),
        ("share_dilution_5y", "low", 0.3),
        ("divyield", "high", 0.2),
        top_n=TOP_N,
    ),
    "low_volatility": Ranking(
        ("volatility_20", "low", 0.5),
        ("roe_volatility_5y", "low", 0.3),
        ("interest_coverage", "high", 0.2),
        top_n=TOP_N,
    ),
    "profit_growth": Ranking(
        ("gross_profitability", "high", 0.4),
        ("revenue_growth_yoy", "high", 0.3),
        ("opinc_growth_yoy", "high", 0.3),
        top_n=TOP_N,
    ),
}

SIGNAL_DAYS = calendar.schedule("2016-01-01", "2025-01-01", freq="QS")
walk = WalkForward(universe, ForwardReturns(252), benchmark="SPY")
variants = {
    "filtered baseline": quality,
    f"random {TOP_N} (control)": _Chain(quality, _RandomCut(TOP_N)),
    **{
        f"{name} top {TOP_N}": _Chain(quality, composite)
        for name, composite in COMPOSITES.items()
    },
}

print(f"\nFIVE COMPOSITES vs A RANDOM CUT ({len(SIGNAL_DAYS)} quarters, top_n={TOP_N})")
results = walk.compare(SIGNAL_DAYS, variants, additions=attach_signals)
for label in variants:
    rows = results[results.variant == label]
    if rows.empty:
        continue
    summary = WalkForward.summarize(rows)
    print(
        f"  {label:<26} measured(median)={rows.measured.median():>5.0f}   "
        f"mean excess {summary['median_excess']:+.2%}   "
        f"dates beat bench {summary['pct_dates_beat_benchmark']:.1%}"
    )
