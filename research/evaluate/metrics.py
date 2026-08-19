"""Pluggable per-date evaluation statistics.

``WalkForward`` always reports the six figures §6.9 requires; an ``EvalMetric``
adds more without editing the harness, the way ``RankMetric`` extends a blend.
Built-ins answer three questions: what the population returned, whether its
score ordered those returns, and whether the picks are one bet or many.

Every built-in returns NaN where the answer is undefined rather than a number.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Spearman on a handful of names is noise wearing a correlation's clothing.
MIN_RANK_OBSERVATIONS = 20

# A decile of fewer than this leaves buckets too thin to mean anything.
MIN_DECILE_OBSERVATIONS = 30

# A correlation drawn from a couple of weeks of sessions is not one.
MIN_PANEL_SESSIONS = 30

_DECILE = 10


@dataclass(frozen=True)
class EvalContext:
    """Everything one date's metrics may read.

    ``measured`` carries ``forward_return`` and ``complete`` always, ``score``
    and ``sector`` only when the selection held them. ``panel`` is the
    daily-return series behind the window, None unless a metric declared
    ``needs_panel`` — it is a far larger query than the rest of a date.
    """

    measured: pd.DataFrame
    benchmark_return: float
    panel: pd.DataFrame | None = None


@dataclass(frozen=True)
class EvalMetric:
    """One named statistic computed over a single date's context.

    ``name`` becomes the report column; ``needs_panel`` is what makes the
    harness fetch ``context.panel``. A metric missing a column it needs should
    return NaN, not raise, so one unscored variant cannot abort a sweep.
    Frozen, so one metric is reusable across every date of a sweep.
    """

    name: str
    fn: Callable[[EvalContext], float]
    needs_panel: bool = False

    def __post_init__(self) -> None:
        """Reject a blank name or a non-callable function.

        :raises ValueError: for either, since both otherwise fail far from
            here — a bad name as a missing column, a bad fn inside the loop.
        """
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("metric name must be a non-empty string")
        if not callable(self.fn):
            raise ValueError(f"metric {self.name!r} fn must be callable")


def _scored_pairs(frame: pd.DataFrame, minimum: int) -> pd.DataFrame | None:
    """Return the score/return pairs worth measuring, or None if too few."""
    if "score" not in frame.columns:
        return None
    paired = frame[["score", "forward_return"]].dropna()
    return paired if len(paired) >= minimum else None


def _information_coefficient(context: EvalContext) -> float:
    """Rank correlation between the selection score and the forward return.

    Whether the ranking had ordering skill: +1 ranked the winners first, 0
    carried no information, negative was inverted. Spearman because a score is
    a percentile blend, so only its order is meaningful.
    """
    paired = _scored_pairs(context.measured, MIN_RANK_OBSERVATIONS)
    if paired is None:
        return float("nan")
    # Pearson over ranks is Spearman, and avoids pandas' scipy-backed
    # method="spearman" for a correlation this project can compute itself.
    return paired["score"].rank().corr(paired["forward_return"].rank())


def _top_minus_bottom_decile(context: EvalContext) -> float:
    """Mean return of the best-scoring tenth less that of the worst-scoring.

    A score can order the middle well and still fail at the extremes, which is
    where a concentrated portfolio lives.
    """
    paired = _scored_pairs(context.measured, MIN_DECILE_OBSERVATIONS)
    if paired is None:
        return float("nan")
    size = len(paired) // _DECILE
    top = paired.nlargest(size, "score")["forward_return"].mean()
    bottom = paired.nsmallest(size, "score")["forward_return"].mean()
    return top - bottom


def _median_return(context: EvalContext) -> float:
    """Median forward return: the typical holding, not the average one.

    A few multi-baggers can carry ``mean_return`` alone, flattering a rule that
    was wrong about nearly everything it picked.
    """
    return context.measured["forward_return"].median()


def _return_dispersion(context: EvalContext) -> float:
    """Return the standard deviation of forward returns across the population.

    Wide dispersion means the mean weakly describes any single position.
    """
    return context.measured["forward_return"].std(ddof=0)


def _avg_pairwise_correlation(context: EvalContext) -> float:
    """Mean correlation between every pair of selected securities.

    Whether a population is many bets or one repeated: near 0 the picks move
    independently, near 1 they are effectively one position. Broad equity
    screens sit above 0 on the market factor alone, so compare across variants
    rather than against zero.
    """
    panel = context.panel
    if panel is None or panel.shape[1] < 2 or len(panel) < MIN_PANEL_SESSIONS:
        return float("nan")
    correlations = panel.corr(min_periods=MIN_PANEL_SESSIONS).to_numpy()
    if correlations.shape[0] < 2:
        return float("nan")
    upper = correlations[np.triu_indices(correlations.shape[0], k=1)]
    return float(np.nanmean(upper)) if np.isfinite(upper).any() else float("nan")


def _sector_concentration(context: EvalContext) -> float:
    """Herfindahl index of the population's sector shares.

    The cheap companion to the correlation metric: no panel, only a ``sector``
    column. 1 when every name shares a sector, approaching 0 as they spread, so
    its reciprocal is an effective sector count — 0.25 behaves like four.
    """
    frame = context.measured
    if "sector" not in frame.columns or frame.empty:
        return float("nan")
    shares = frame["sector"].value_counts(normalize=True, dropna=False)
    return float((shares**2).sum())


INFORMATION_COEFFICIENT = EvalMetric(
    "information_coefficient", _information_coefficient
)
TOP_MINUS_BOTTOM_DECILE = EvalMetric(
    "top_minus_bottom_decile", _top_minus_bottom_decile
)
MEDIAN_RETURN = EvalMetric("median_return", _median_return)
RETURN_DISPERSION = EvalMetric("return_dispersion", _return_dispersion)
AVG_PAIRWISE_CORRELATION = EvalMetric(
    "avg_pairwise_correlation", _avg_pairwise_correlation, needs_panel=True
)
SECTOR_CONCENTRATION = EvalMetric("sector_concentration", _sector_concentration)

RANK_QUALITY = (INFORMATION_COEFFICIENT, TOP_MINUS_BOTTOM_DECILE)

# AVG_PAIRWISE_CORRELATION triggers the panel query; drop it for the cheap half.
CONCENTRATION = (AVG_PAIRWISE_CORRELATION, SECTOR_CONCENTRATION)
