"""Do weighted composites beat a random cut at the same concentration?

Five composites — momentum, value, shareholder yield, low volatility, profit
growth — each cut to the same top_n and compared against a seeded random
selection from the same filtered population. The random control is the point:
without it, a composite that merely inherits the filter's edge looks skillful.
Lifted out of research/ranking.py, where it lived as a __main__ block.

Run: uv run python -m experiments.composite_vs_random
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

# ── coverage: a metric a security lacks is renormalised away, not zeroed ──
print("\nCOVERAGE (share of requested weight actually present)")
print(ranked["coverage"].value_counts().sort_index(ascending=False).head().to_string())

# ── grouped: best per industry rather than best overall ──────────────────
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


# ── five candidate composites against a concentration control ───────────
# The roic/fcf_yield/accruals blend carried no information: its top 200 AND
# its bottom 200 both landed ~2.3pp below the filtered baseline, so the cut
# was measuring concentration, not quality. Every variant here therefore
# holds the same prefilter and the same top_n, and a seeded random cut of
# the same size runs alongside as the control. The bar a composite has to
# clear is the random cut, not the baseline — beating -6.7% is impossible
# at this concentration if any 200-name cut costs ~2.3pp by itself.
class _Chain:
    """Apply `.apply(frame)` steps in order, so `walk.compare` sees a
    filter-then-rank variant as one object.

    Local to this experiment on purpose: composing a *spec* is the
    orchestrator's job, and it composes at the screen level (universe,
    signals, score, filter, cut). This composes two frame transforms for a
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
    """Seeded arbitrary selection at the experiment's concentration.

    Deterministic across reruns (fixed seed), different picks per date
    (each date hands it a different frame).
    """

    def __init__(self, n: int, seed: int = 0) -> None:
        self.n, self.seed = n, seed

    def __repr__(self) -> str:
        return f"_RandomCut(n={self.n})"

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.sample(n=min(self.n, len(frame)), random_state=self.seed)


TOP_N = 200
COMPOSITES = {
    # Jegadeesh & Titman's twelve-month winners, George & Hwang's proximity
    # to the 52-week high, and the volatility-scaled variant of the same
    # idea. pct_from_52w_high lives in [-1, 0], so "high" means near the
    # high.
    "momentum": Ranking(
        ("vol_adjusted_momentum", "high", 0.4),
        ("return_252d", "high", 0.3),
        ("pct_from_52w_high", "high", 0.3),
        top_n=TOP_N,
    ),
    # Cheapness. The prefilter requires positive net income, so "low pe"
    # ranks cheap earners rather than crowning loss-makers cheapest.
    "value": Ranking(
        ("fcf_yield", "high", 0.4),
        ("pe", "low", 0.3),
        ("ps", "low", 0.3),
        top_n=TOP_N,
    ),
    # Boudoukh et al.: net payout (dividends + buybacks - issuance) carries
    # more information than dividend yield alone; a shrinking share count
    # is the five-year version of the same statement.
    "shareholder_yield": Ranking(
        ("net_payout_yield", "high", 0.5),
        ("share_dilution_5y", "low", 0.3),
        ("divyield", "high", 0.2),
        top_n=TOP_N,
    ),
    # Ang et al.'s low-volatility anomaly plus earnings stability.
    # interest_coverage rather than de, whose negative-equity values would
    # rank distress as "least levered".
    "low_volatility": Ranking(
        ("volatility_20", "low", 0.5),
        ("roe_volatility_5y", "low", 0.3),
        ("interest_coverage", "high", 0.2),
        top_n=TOP_N,
    ),
    # Novy-Marx gross profitability, with top-line and operating growth.
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
