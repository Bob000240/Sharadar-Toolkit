"""Score and order a population by a weighted blend of percentile ranks.

Percentiles rather than raw values, because the fields being blended have
incommensurable units: a ROIC of 0.15 and a P/E of 12 cannot be averaged, but
their cross-sectional ranks can.

Ranks are computed over whatever population is handed to ``score``, so the
caller decides the comparison set. Ranking the filtered survivors makes a score
mean "best of those that qualified"; ranking the whole universe makes it mean
"best overall". Neither is wrong, but they are different questions and the
number changes meaning silently between them.

``_DIRECTIONS`` is the whitelist of accepted directions. Validating against it
matters because the direction is applied by an equality test, so an unrecognised
spelling would otherwise be treated as "high" and invert a factor in silence.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from research.signals.sig import Signals

_DIRECTIONS = {"high", "low"}

_DEFAULT_MIN_COVERAGE = 0.5


@dataclass(frozen=True)
class RankMetric:
    """One field, which end of it is good, and how much it counts.

    Instance variables are ``field``, ``direction`` — "high" or "low" — and
    ``weight``, a finite positive float defaulting to 1.0.

    Frozen, so one metric can be reused across every signal day of a sweep
    without a caller mutating it mid-run.
    """

    field: str
    direction: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        """Reject malformed metrics and coerce the weight to float.

        Raise ValueError for a blank field, an unregistered direction, or a
        weight that is not finite and positive. Lower-is-better is expressed
        with ``direction="low"`` and never with a negative weight, which would
        break the coverage renormalisation in ``Ranking.score``.
        """
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
    """Normalise one caller-supplied metric into a RankMetric.

    Accept a RankMetric unchanged, or a ``(field, direction[, weight])`` tuple
    where an omitted weight defaults to 1.0. Raise ValueError for anything else.
    """
    if isinstance(metric, RankMetric):
        return metric
    if not isinstance(metric, tuple) or len(metric) not in {2, 3}:
        raise ValueError(
            "each metric must be RankMetric or a (field, direction[, weight]) tuple"
        )
    return RankMetric(*metric)


class Ranking:
    """A weighted blend of percentile ranks over a population.

    Public methods are ``score``, which attaches percentiles and a blended
    score, ``cut``, which orders and truncates an already-scored frame,
    ``apply``, which does both over one population, and ``select``, which
    returns just the surviving tickers. Instance variables are ``metrics``,
    ``group_by``, ``top_n``, ``min_coverage``, and ``positive_only``.

    ``group_by`` names a column to rank within, such as sector, instead of
    across the whole population. ``positive_only`` names fields where a
    non-positive value is undefined rather than merely extreme: a loss-maker's
    P/E is masked out of the percentile rather than ranked as cheapest. Callers
    driven by the field registry pass ``registry.positive_only(fields)``; a
    hand-built Ranking states it explicitly.
    """

    def __init__(
        self,
        *metrics: RankMetric | tuple,
        group_by: str | None = None,
        top_n: int | None = None,
        min_coverage: float = _DEFAULT_MIN_COVERAGE,
        positive_only: tuple[str, ...] = (),
    ) -> None:
        """Coerce each metric and store the blend's settings.

        Raise ValueError when no metric is supplied, when ``top_n`` is below 1,
        when ``min_coverage`` falls outside [0, 1], or when a field appears in
        more than one metric.
        """
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
        self.positive_only = tuple(positive_only)

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
        """Return the metrics with the grouping and cut settings."""
        parts = [f"({m.field!r}, {m.direction!r}, {m.weight})" for m in self.metrics]
        return (
            f"Ranking({', '.join(parts)}, group_by={self.group_by!r}, "
            f"top_n={self.top_n})"
        )

    def _validate_fields(self, frame: pd.DataFrame) -> None:
        """Raise KeyError if a metric field or the group column is missing.

        Every missing metric field is reported at once, so a misspelled spec is
        fixed in one pass instead of one error per run.
        """
        missing = sorted({m.field for m in self.metrics} - set(frame.columns))
        if missing:
            raise KeyError(
                f"rank fields are not attached to the frame: {missing}. "
                "Attach them first with attach_signals(frame, signal_day)."
            )
        if self.group_by is not None and self.group_by not in frame.columns:
            raise KeyError(f"group_by column {self.group_by!r} is not in the frame")

    def _percentile(self, frame: pd.DataFrame, field: str) -> pd.Series:
        """Return a direction-free percentile in [0, 100] for one field.

        Ranks within ``group_by`` when one is set, across the whole frame
        otherwise. A field listed in ``positive_only`` has its non-positive
        values masked to NaN first, so they are absent from the rank rather than
        occupying its cheap end.
        """
        values = frame[field]
        if field in self.positive_only:
            values = pd.to_numeric(values, errors="coerce").where(lambda v: v > 0)
        if self.group_by is None:
            return Signals.rank_pct(values)
        return Signals.rank_within_sector(values, frame[self.group_by])

    def score(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach per-metric percentiles, ``coverage``, and ``score``.

        Adds ``{field}_pct`` for every metric, already direction-adjusted so 100
        is always the good end. ``coverage`` is the share of requested weight a
        security actually carries data for, and the blend is renormalised by it,
        so a security missing one metric is scored on the others rather than
        handed a zero. Below ``min_coverage`` the blend is too thin to mean
        anything and the row is dropped rather than ranked worst.

        Split out from ``apply`` because the population a score is computed over
        and the population it is cut from are not always the same. Scoring the
        whole structural universe and cutting after elective filters makes a
        score of 82 mean the same thing across screens; scoring post-filter
        would make every score relative to a different reference set.

        Return the scored rows, without ordering and without a ``top_n`` cut.
        """
        self._validate_fields(frame)
        if frame.empty:
            return frame.assign(score=[], coverage=[])

        ranked = frame.copy()
        weighted_total = pd.Series(0.0, index=ranked.index)
        available_weight = pd.Series(0.0, index=ranked.index)

        for metric in self.metrics:
            percentile = self._percentile(ranked, metric.field)
            if metric.direction == "low":
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

        score = weighted_total / available_weight.where(available_weight > 0)
        ranked["score"] = score.where(ranked["coverage"] >= self.min_coverage)

        return ranked[ranked["score"].notna()]

    def cut(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Order an already-scored frame and keep the top ``top_n`` per group.

        Ties share the better rank rather than being ordered by row position.
        Kept separate from ``score`` so the cut can be taken over a filtered
        subset of the population the score was computed on.

        Return the ordered rows with a ``rank`` column added. Raise KeyError
        when ``frame`` carries no ``score`` column.
        """
        if "score" not in frame.columns:
            raise KeyError(
                "frame has no 'score' column; call Ranking.score(frame) first"
            )
        ranked = frame
        if ranked.empty:
            return ranked.assign(rank=[])

        if self.group_by is None:
            ranked = ranked.sort_values("score", ascending=False)
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

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Score and cut over one population.

        The standalone case, where the frame handed in is both the reference set
        the ranks are computed against and the candidate set the cut is taken
        from.
        """
        return self.cut(self.score(frame))

    def select(self, frame: pd.DataFrame) -> pd.Series:
        """Return just the surviving tickers, for a population hook."""
        return self.apply(frame)["ticker"]
