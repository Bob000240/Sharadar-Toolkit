from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from research.signals.sig import Signals

_DIRECTIONS = {"high", "low"}

_DEFAULT_MIN_COVERAGE = 0.5


@dataclass(frozen=True)
class RankMetric:
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
    def __init__(
        self,
        *metrics: RankMetric | tuple,
        group_by: str | None = None,
        top_n: int | None = None,
        min_coverage: float = _DEFAULT_MIN_COVERAGE,
        positive_only: tuple[str, ...] = (),
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
        # Fields where a non-positive value is UNDEFINED rather than extreme — a
        # loss-maker's PE must be masked, not ranked as "cheapest". Callers
        # driven by the field registry pass registry.positive_only(fields); a
        # hand-built Ranking states it explicitly.
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
        if field in self.positive_only:
            values = pd.to_numeric(values, errors="coerce").where(lambda v: v > 0)
        if self.group_by is None:
            return Signals.rank_pct(values)
        return Signals.rank_within_sector(values, frame[self.group_by])

    def score(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach `{field}_pct`, `coverage`, and `score`; drop rows below
        `min_coverage`. No ordering and no `top_n` cut.

        Split out from `apply` because the population a score is computed over
        and the population it is cut from are not always the same. Scoring the
        whole structural universe and cutting after elective filters makes a
        score of 82 mean the same thing across screens; scoring post-filter
        would make every score relative to a different reference set.
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
        """Order an already-scored frame and keep the top `top_n` per group.

        Expects `score` to be present — `score()` puts it there. Kept separate so
        the cut can be taken over a filtered subset of the population the score
        was computed on.
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
        """Score and cut over the same population — the standalone case, where
        the frame handed in is both the reference set and the candidate set."""
        return self.cut(self.score(frame))

    def select(self, frame: pd.DataFrame) -> pd.Series:
        return self.apply(frame)["ticker"]
