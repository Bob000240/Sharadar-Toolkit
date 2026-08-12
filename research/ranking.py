from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from data.signals.sig import Signals

# Higher-is-better or lower-is-better. Direction is a judgment about what a
# field means, which is why it lives here rather than in the signal layer:
# `rank_pct` emits a direction-free percentile, and this module decides whether
# the top or the bottom of that range is the good end.
_DIRECTIONS = {"high", "low"}

_DEFAULT_MIN_COVERAGE = 0.5


@dataclass(frozen=True)
class RankMetric:
    """One field, which end of it is good, and how much it counts."""

    field: str
    direction: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not self.field.strip():
            raise ValueError("rank field must be a non-empty string")
        if self.direction not in _DIRECTIONS:
            raise ValueError(
                f"unregistered direction {self.direction!r}; use one of "
                f"{tuple(sorted(_DIRECTIONS))}"
            )
        weight = float(self.weight)
        if weight <= 0 or weight != weight or weight == float("inf"):
            raise ValueError(
                f"weight must be finite and positive; got {self.weight!r}. "
                "Lower-is-better is expressed with direction='low', never a "
                "negative weight."
            )
        object.__setattr__(self, "weight", weight)


def _coerce_metric(metric: object) -> RankMetric:
    if isinstance(metric, RankMetric):
        return metric
    if not isinstance(metric, tuple) or len(metric) not in {2, 3}:
        raise ValueError(
            "each metric must be RankMetric or a (field, direction[, weight]) tuple"
        )
    return RankMetric(*metric)


class Ranking:
    """Score and order a population by a weighted blend of percentile ranks.

        Ranking(("roic", "high", 0.6), ("pe", "low", 0.4), group_by="famaindustry")

    Percentiles rather than raw values, because the fields being blended have
    incommensurable units — a ROIC of 0.15 and a P/E of 12 cannot be averaged,
    but their cross-sectional ranks can.

    Ranks are computed over the population handed to `apply`, before any `top_n`
    cut. That means the caller decides the comparison set by choosing what to
    pass in: rank the filtered survivors and a score means "best of those that
    qualified"; rank the whole universe and it means "best overall". Neither is
    wrong, but they are different questions, and the score silently changes
    meaning between them.
    """

    def __init__(
        self,
        *metrics: RankMetric | tuple,
        group_by: str | None = None,
        top_n: int | None = None,
        min_coverage: float = _DEFAULT_MIN_COVERAGE,
    ) -> None:
        if not metrics:
            raise ValueError("Ranking requires at least one metric")
        if top_n is not None and top_n < 1:
            raise ValueError(f"top_n must be at least 1; got {top_n}")
        if not 0 <= min_coverage <= 1:
            raise ValueError(f"min_coverage must be in [0, 1]; got {min_coverage}")

        self.metrics = tuple(_coerce_metric(metric) for metric in metrics)
        self.group_by = group_by
        self.top_n = top_n
        self.min_coverage = min_coverage

        duplicates = sorted(
            {
                metric.field
                for metric in self.metrics
                if sum(other.field == metric.field for other in self.metrics) > 1
            }
        )
        if duplicates:
            raise ValueError(f"fields appear more than once in metrics: {duplicates}")

    def __repr__(self) -> str:
        parts = [f"({m.field!r}, {m.direction!r}, {m.weight})" for m in self.metrics]
        return (
            f"Ranking({', '.join(parts)}, group_by={self.group_by!r}, "
            f"top_n={self.top_n})"
        )

    def _validate_fields(self, frame: pd.DataFrame) -> None:
        missing = sorted({m.field for m in self.metrics} - set(frame.columns))
        if missing:
            raise KeyError(
                f"rank fields are not attached to the frame: {missing}. "
                "Attach them first with attach_signals(frame, signal_day)."
            )
        if self.group_by is not None and self.group_by not in frame.columns:
            raise KeyError(f"group_by column {self.group_by!r} is not in the frame")

    def _percentile(self, frame: pd.DataFrame, field: str) -> pd.Series:
        """Direction-free percentile in [0, 100], within group when asked."""
        values = frame[field]
        if self.group_by is None:
            return Signals.rank_pct(values)
        return Signals.rank_within_sector(values, frame[self.group_by])

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return `frame` with per-metric percentiles, a score, and a rank.

        Adds `{field}_pct` for every metric (already direction-adjusted, so 100
        is always the good end), plus `score`, `coverage`, and `rank`. Rows are
        ordered best-first; `top_n` cuts per group when grouping.
        """
        self._validate_fields(frame)
        if frame.empty:
            return frame.assign(score=[], coverage=[], rank=[])

        ranked = frame.copy()
        weighted_total = pd.Series(0.0, index=ranked.index)
        available_weight = pd.Series(0.0, index=ranked.index)

        for metric in self.metrics:
            percentile = self._percentile(ranked, metric.field)
            if metric.direction == "low":
                # rank_pct is direction-free, so invert rather than negate the
                # weight — 100 must always mean "good" for the blend to add up.
                percentile = 100.0 - percentile
            ranked[f"{metric.field}_pct"] = percentile

            present = percentile.notna()
            weighted_total = weighted_total.add(
                percentile.fillna(0.0) * metric.weight, fill_value=0.0
            )
            available_weight = available_weight.add(
                present * metric.weight, fill_value=0.0
            )

        total_weight = sum(metric.weight for metric in self.metrics)
        ranked["coverage"] = available_weight / total_weight

        # Renormalise by the weight actually present, so a security missing one
        # metric is scored on the others rather than being handed a zero for it.
        # Below `min_coverage` the blend is too thin to mean anything and the
        # score is null — which drops the row rather than ranking it as worst.
        score = weighted_total / available_weight.where(available_weight > 0)
        ranked["score"] = score.where(ranked["coverage"] >= self.min_coverage)

        ranked = ranked[ranked["score"].notna()]
        if ranked.empty:
            return ranked.assign(rank=[])

        if self.group_by is None:
            ranked = ranked.sort_values("score", ascending=False)
            # method="min" so tied scores share the better rank rather than
            # being ordered arbitrarily by row position.
            ranked["rank"] = ranked["score"].rank(ascending=False, method="min")
        else:
            ranked = ranked.sort_values(
                [self.group_by, "score"], ascending=[True, False]
            )
            ranked["rank"] = ranked.groupby(self.group_by)["score"].rank(
                ascending=False, method="min"
            )

        if self.top_n is not None:
            ranked = ranked[ranked["rank"] <= self.top_n]

        return ranked

    def select(self, frame: pd.DataFrame) -> pd.Series:
        """Just the surviving tickers, for `WalkForward`'s population hook."""
        return self.apply(frame)["ticker"]


class Pipeline:
    """Apply steps in order, each one narrowing or ordering the last.

        Pipeline(Filters(...), Ranking(...))

    Duck-typed on `.apply(frame) -> frame`, so this composes `Filters` and
    `Ranking` without either importing the other, and `WalkForward.compare`
    accepts the result as just another variant.
    """

    def __init__(self, *steps) -> None:
        if not steps:
            raise ValueError("Pipeline requires at least one step")
        self.steps = steps

    def __repr__(self) -> str:
        return f"Pipeline({', '.join(repr(step) for step in self.steps)})"

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        for step in self.steps:
            frame = step.apply(frame)
        return frame


if __name__ == "__main__":
    import pandas as pd

    from research.evaluate.forward import ForwardReturns
    from research.evaluate.walk_forward import WalkForward
    from research.filters import Filters, attach_signals
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
    print(
        ranked["coverage"].value_counts().sort_index(ascending=False).head().to_string()
    )

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

    SIGNAL_DAYS = pd.date_range("2016-01-01", "2025-01-01", freq="QS").tolist()
    walk = WalkForward(universe, ForwardReturns(252), benchmark="SPY")
    variants = {
        "filtered baseline": quality,
        f"random {TOP_N} (control)": Pipeline(quality, _RandomCut(TOP_N)),
        **{
            f"{name} top {TOP_N}": Pipeline(quality, composite)
            for name, composite in COMPOSITES.items()
        },
    }

    print(
        f"\nFIVE COMPOSITES vs A RANDOM CUT "
        f"({len(SIGNAL_DAYS)} quarters, top_n={TOP_N})"
    )
    results = walk.compare(SIGNAL_DAYS, variants, additions=attach_signals)
    for label in variants:
        rows = results[results.variant == label]
        if rows.empty:
            continue
        summary = WalkForward.summarize(rows)
        print(
            f"  {label:<26} n(median)={rows.n.median():>5.0f}   "
            f"mean excess {summary['median_excess']:+.2%}   "
            f"dates beat bench {summary['pct_dates_beat_benchmark']:.1%}"
        )
