"""Screen orchestration: compose a universe, score it, filter it, cut it.

`run(spec, signal_day)` is the single entry point a CLI, an agent, or the
backtest harness calls. Everything it needs is in the `ScreenSpec` — so the same
object a user builds is the object the harness replays, which is the only way to
guarantee that what you tested is what you screened.

Order of operations, and each step is deliberate:

  1. STRUCTURAL universe — non-negotiable listing/recency rules (`Universe`)
  2. derive features — only the sources the spec actually references
  3. SCORE over the whole structural universe
  4. ELECTIVE filters — the spec's own conditions, with a per-filter funnel
  5. cut to the top N

Step 3 before step 4 is the load-bearing choice. Scoring the full universe
before filtering makes a score of 82 mean the same thing no matter which filters
the spec picked; scoring afterwards would make every score relative to a
different reference set and silently incomparable between screens. It is also a
behavioural difference from `SLEntryScreener`, which ranks inside an
already-narrowed set — expect different numbers from the two.

This module composes; it does not compute. Universe rules live in
`research.universe`, feature assembly in `research.filters.attach_signals`,
predicates in `research.filters`, scoring in `research.ranking`, and the field
catalog in `research.registry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

import research.calendar as calendar
import research.registry as registry
from research.filters import SIGNAL_SOURCES, Filters, attach_signals
from research.ranking import Ranking
from research.signals.sig import Signals
from research.universe import Universe

# The registry names an event field's source "event"; the signal loader
# registers the chain as "events". One rename would remove this, but it would
# touch both the registry's 57 field declarations and every caller of
# attach_signals, so the mapping is stated here instead.
_SOURCE_ALIASES = {"event": "events"}


@dataclass(frozen=True)
class ScreenSpec:
    """A complete, serializable screen.

    `rank=None` filters without scoring — useful for asking "how many names even
    qualify?" without committing to a ranking judgment.
    """

    name: str = "unnamed"
    description: str = ""
    universe: Universe = field(default_factory=Universe)
    filters: Filters | None = None
    rank: Ranking | None = None

    def fields(self) -> tuple[str, ...]:
        """Every registry field this spec references, filters and rank alike."""
        referenced: list[str] = []
        if self.filters is not None:
            referenced.extend(c.field for c in self.filters.conditions)
        if self.rank is not None:
            referenced.extend(m.field for m in self.rank.metrics)
        return tuple(dict.fromkeys(referenced))


@dataclass(frozen=True)
class ScreenResult:
    """A run, with enough context to reproduce and audit it."""

    signal_day: date
    frame: pd.DataFrame  # scored and cut candidates (or merely filtered)
    funnel: pd.DataFrame  # per-filter attrition
    universe_size: int  # structural universe, before elective filters
    spec: ScreenSpec

    def __len__(self) -> int:
        return len(self.frame)


def validate(spec: ScreenSpec) -> list[str]:
    """Every problem with a spec, checked against the registry alone — no
    database, no frame. A CLI or an agent should call this before submitting."""
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
    """The derive chains a set of fields needs, so a screen computes only what it
    was asked for. An empty spec still loads nothing rather than everything."""
    needed = {
        _SOURCE_ALIASES.get(source, source) for source in registry.sources(fields)
    }
    unknown = sorted(needed - set(SIGNAL_SOURCES))
    if unknown:
        raise ValueError(
            f"registry names signal sources the loader does not provide: {unknown}"
        )
    # Preserve SIGNAL_SOURCES order so the merge sequence is deterministic.
    return tuple(name for name in SIGNAL_SOURCES if name in needed)


def run(spec: ScreenSpec, signal_day) -> ScreenResult:
    """Run `spec` as of `signal_day`.

    Raises on an invalid spec rather than returning something plausible-looking
    from a misspelled field. `signal_day` is aligned onto a real trading session
    first, so a request made on a weekend reports the session it actually used.
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
        # Registry-driven masking: a spec that ranks on `pe` gets loss-makers
        # excluded from the percentile automatically, rather than each strategy
        # remembering to say so.
        scorer = Ranking(
            *spec.rank.metrics,
            group_by=spec.rank.group_by,
            top_n=spec.rank.top_n,
            min_coverage=spec.rank.min_coverage,
            positive_only=registry.positive_only([m.field for m in spec.rank.metrics]),
        )
        before = len(frame)
        frame = scorer.score(frame)
        # Scoring is itself attrition: a name carrying too few of the ranked
        # fields cannot be scored and leaves the population here, before any
        # elective filter sees it. Reported as a funnel row so the counts
        # reconcile against universe_size instead of starting mid-air.
        scoring_attrition.append(
            {
                "condition": f"scored (coverage >= {spec.rank.min_coverage:g})",
                "before": before,
                "after": len(frame),
                "dropped": before - len(frame),
                "dropped_for_null": before - len(frame),
            }
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
