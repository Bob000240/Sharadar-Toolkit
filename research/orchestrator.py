"""Screen orchestration: compose a universe, score it, filter it, cut it.

``run(spec, signal_day)`` is the single entry point. The order is deliberate:
structural universe, derive only the referenced sources, score over the whole
universe, apply elective filters, cut to top N.

Scoring before filtering is the load-bearing choice — it makes a score of 82
mean the same thing across screens, where scoring afterwards would make every
score relative to a different reference set.

This module composes; it does not compute. ``_SOURCE_ALIASES`` reconciles one
naming mismatch: the registry says "event", the signal loader says "events".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

import research.calendar as calendar
import research.registry as registry
from research.filters import SIGNAL_SOURCES, Filters, attach_signals, funnel_row
from research.ranking import Ranking
from research.signals.sig import Signals
from research.universe import Universe

_SOURCE_ALIASES = {"event": "events"}


@dataclass(frozen=True)
class ScreenSpec:
    """A complete, serialisable screen.

    ``filters=None`` scores without narrowing; ``rank=None`` filters without
    scoring, answering "how many names even qualify?" without committing to a
    ranking judgment. Frozen, so the spec that was tested is the spec that runs.
    """

    name: str = "unnamed"
    description: str = ""
    universe: Universe = field(default_factory=Universe)
    filters: Filters | None = None
    rank: Ranking | None = None

    def fields(self) -> tuple[str, ...]:
        """Return every registry field this spec references, in first-use order.

        Covers filter conditions and rank metrics alike, deduplicated, so the
        caller can resolve exactly which derive chains the spec needs.
        """
        referenced: list[str] = []
        if self.filters is not None:
            referenced.extend(c.field for c in self.filters.conditions)
        if self.rank is not None:
            referenced.extend(m.field for m in self.rank.metrics)
        return tuple(dict.fromkeys(referenced))


@dataclass(frozen=True)
class ScreenResult:
    """One screen run, with enough context to reproduce and audit it.

    Instance variables are ``signal_day``, the session actually used;
    ``frame``, the scored and cut candidates, or merely the filtered ones when
    the spec has no rank; ``funnel``, the per-filter attrition; ``universe_size``,
    the structural universe before any elective filter; and ``spec``.
    """

    signal_day: date
    frame: pd.DataFrame
    funnel: pd.DataFrame
    universe_size: int
    spec: ScreenSpec

    def __len__(self) -> int:
        """Return how many candidates survived."""
        return len(self.frame)


def validate(spec: ScreenSpec) -> list[str]:
    """Return every problem with ``spec``, or an empty list when it is sound.

    Checked against the registry alone, with no database and no frame, so a CLI
    or an agent can call it before submitting. Catches unknown field names and
    fields used in a role the registry does not permit.
    """
    problems: list[str] = []

    if spec.filters is not None:
        for condition in spec.filters.conditions:
            if condition.field not in registry.FIELDS:
                problems.append(f"unknown filter field {condition.field!r}")
            elif not registry.get(condition.field).filterable:
                problems.append(f"field {condition.field!r} is not filterable")

    if spec.rank is not None:
        for metric in spec.rank.metrics:
            if metric.field not in registry.FIELDS:
                problems.append(f"unknown rank field {metric.field!r}")
            elif not registry.get(metric.field).rankable:
                problems.append(f"field {metric.field!r} is not rankable")

    return problems


def _sources(fields: tuple[str, ...]) -> tuple[str, ...]:
    """Return the derive chains ``fields`` requires, in merge order.

    A screen computes only what it was asked for, and an empty spec loads
    nothing rather than everything. The order follows ``SIGNAL_SOURCES`` so the
    merge sequence is deterministic. Raise ValueError when the registry names a
    source the signal loader does not provide.
    """
    needed = {
        _SOURCE_ALIASES.get(source, source) for source in registry.sources(fields)
    }
    unknown = sorted(needed - set(SIGNAL_SOURCES))
    if unknown:
        raise ValueError(
            f"registry names signal sources the loader does not provide: {unknown}"
        )
    return tuple(name for name in SIGNAL_SOURCES if name in needed)


def _positive_only(rank: Ranking) -> tuple[str, ...]:
    """Return the fields whose non-positive values must be masked from a rank.

    The union of what the registry declares and what the Ranking was built with.
    The registry is authoritative, but a caller's own entries are kept rather than
    discarded, so a hand-built Ranking is amended instead of overruled.
    """
    declared = registry.positive_only([metric.field for metric in rank.metrics])
    return tuple(dict.fromkeys(rank.positive_only + declared))


def run(spec: ScreenSpec, signal_day) -> ScreenResult:
    """Run ``spec`` as of ``signal_day`` and return a ScreenResult.

    ``signal_day`` is aligned onto a real trading session first. Scoring is itself
    attrition: a name carrying too few ranked fields leaves before any elective
    filter sees it, so it is the funnel's first row and the counts reconcile
    against ``universe_size``.

    :raises ValueError: for an invalid spec, rather than returning something
        plausible-looking from a misspelled field.
    """
    problems = validate(spec)
    if problems:
        raise ValueError(f"invalid ScreenSpec: {'; '.join(problems)}")

    signal_day = calendar.align(signal_day)
    universe = spec.universe.run(signal_day)

    def result(frame: pd.DataFrame, funnel: pd.DataFrame) -> ScreenResult:
        return ScreenResult(
            signal_day=signal_day,
            frame=frame,
            funnel=funnel,
            universe_size=len(universe),
            spec=spec,
        )

    if universe.empty:
        return result(universe, pd.DataFrame())

    referenced = spec.fields()
    frame = attach_signals(universe, signal_day, _sources(referenced))
    frame = frame.set_index("ticker", drop=False)

    scoring_attrition: list[dict] = []
    if spec.rank is not None:
        if spec.rank.group_by == "sector":
            frame = Signals.attach_sectors(frame)
        scorer = Ranking(
            *spec.rank.metrics,
            group_by=spec.rank.group_by,
            top_n=spec.rank.top_n,
            min_coverage=spec.rank.min_coverage,
            positive_only=_positive_only(spec.rank),
        )
        before = len(frame)
        frame = scorer.score(frame)
        scoring_attrition.append(
            funnel_row(
                f"scored (coverage >= {spec.rank.min_coverage:g})",
                before,
                len(frame),
                dropped_for_null=before - len(frame),
            )
        )

    if spec.filters is None:
        funnel = pd.DataFrame(scoring_attrition)
    else:
        funnel = pd.concat(
            [pd.DataFrame(scoring_attrition), spec.filters.funnel(frame)],
            ignore_index=True,
        )
        frame = spec.filters.apply(frame)

    if spec.rank is None or frame.empty:
        return result(frame, funnel)

    return result(scorer.cut(frame), funnel)


if __name__ == "__main__":
    spec = ScreenSpec(
        name="quality_at_a_price",
        description="Profitable large caps in an uptrend, best-scoring per sector.",
        filters=Filters(
            ("marketcap", ">=", 1e10),
            ("dollar_volume_20d_avg", ">=", 5e6),
            ("netinccmnusd", ">", 0),
            ("pct_from_sma_200", ">", 0),
        ),
        rank=Ranking(
            ("roic", "high", 0.4),
            ("fcf_yield", "high", 0.3),
            ("pe", "low", 0.3),
            group_by="sector",
            top_n=3,
        ),
    )

    print(f"spec fields: {spec.fields()}")
    print(f"sources needed: {_sources(spec.fields())}")
    print(f"validation problems: {validate(spec) or 'none'}")

    outcome = run(spec, calendar.latest_session())
    print(f"\n{spec.name} as of {outcome.signal_day}")
    print(f"  structural universe {outcome.universe_size:,} -> {len(outcome)} selected")
    print("\nFUNNEL")
    print(outcome.funnel.to_string(index=False))

    if len(outcome):
        columns = ["ticker", "sector", "score", "coverage", "rank"]
        print("\nSELECTED")
        print(
            outcome.frame[columns].to_string(
                index=False, formatters={"score": "{:.1f}".format}
            )
        )

    print("\nAN INVALID SPEC FAILS BEFORE ANY QUERY")
    broken = ScreenSpec(filters=Filters(("marketcapp", ">=", 1e10)))
    print(f"  {validate(broken)}")
