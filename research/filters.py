"""Field/operator/value predicates over an assembled signal frame.

A ``Filters`` object ANDs its conditions. Conditions name fields by string, so
any column a signal source produces is filterable without this module knowing
the name; ``attach_signals`` puts those columns on the frame.

``_NULL_OPERATORS`` and ``_COLLECTION_VALUE_OPERATORS`` must stay in step with
``_OPERATORS``: registering an operator without listing it in the right set
silently skips its validation. ``funnel_row`` is the attrition schema shared
with the orchestrator, so the two stages cannot drift apart.

Every signal service reaches this path through ``SIGNAL_SOURCES``. Their raw
rows stay available directly: registration adds screening rather than replacing
the services.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

import database.source.fundamentals_repo as fundamentals_repo
import database.source.technical_features_repo as technical_features_repo
from research.signals.sig_events import EventSignals
from research.signals.sig_insider import InsiderSignals
from research.signals.sig_institutional import InstitutionalSignals
from research.signals.sig_fundamentals import FundamentalSignals
from research.signals.sig_technical import TechnicalSignals


def _between(series: pd.Series, value: object) -> pd.Series:
    lower, upper = value
    return series.between(lower, upper, inclusive="both")


def _in(series: pd.Series, value: object) -> pd.Series:
    return series.isin(value)


def _not_in(series: pd.Series, value: object) -> pd.Series:
    return ~series.isin(value)


def _is_collection(value: object) -> bool:
    """Return True when ``value`` is a container rather than a scalar.

    Strings and bytes are excluded despite being iterable, because ``"AB" in
    "ABC"`` is a substring test rather than membership.
    """
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes))


def _contains_any(series: pd.Series, value: object) -> pd.Series:
    expected = tuple(value)
    return series.map(
        lambda observed: (
            _is_collection(observed) and any(item in observed for item in expected)
        )
    )


def _contains_all(series: pd.Series, value: object) -> pd.Series:
    expected = tuple(value)
    return series.map(
        lambda observed: (
            _is_collection(observed) and all(item in observed for item in expected)
        )
    )


def _excludes_any(series: pd.Series, value: object) -> pd.Series:
    """Mark rows whose list-valued cell holds none of the excluded items.

    Each cell of ``series`` carries a list rather than a scalar. A cell that is
    not a list fails rather than passes, so a security with unknown events is
    never treated as clean. Return a boolean Series aligned to ``series``.
    """
    excluded = tuple(value)
    return series.map(
        lambda observed: (
            _is_collection(observed) and not any(item in observed for item in excluded)
        )
    )


_OPERATORS = {
    ">=": lambda series, value: series >= value,
    ">": lambda series, value: series > value,
    "<=": lambda series, value: series <= value,
    "<": lambda series, value: series < value,
    "=": lambda series, value: series == value,
    "==": lambda series, value: series == value,
    "!=": lambda series, value: series != value,
    "between": _between,
    "in": _in,
    "not_in": _not_in,
    "contains_any": _contains_any,
    "contains_all": _contains_all,
    "excludes_any": _excludes_any,
    "is_null": lambda series, value: series.isna(),
    "not_null": lambda series, value: series.notna(),
}


_NULL_OPERATORS = {"is_null", "not_null"}
_COLLECTION_VALUE_OPERATORS = {
    "between",
    "in",
    "not_in",
    "contains_any",
    "contains_all",
    "excludes_any",
}

# Narrower than _COLLECTION_VALUE_OPERATORS on purpose: `between` also takes a
# collection but applies to a scalar column, so sharing it would reject `pe`.
MEMBERSHIP_OPERATORS = frozenset({"contains_any", "contains_all", "excludes_any"})
SCALAR_OPERATORS = frozenset(_OPERATORS) - MEMBERSHIP_OPERATORS


@dataclass(frozen=True)
class FilterCondition:
    """One field/operator/value rule applied to an assembled signal frame.

    Instance variables are ``field``, ``operator``, and ``value``. ``value`` is
    None for the null operators and a tuple for the collection operators.

    Frozen, so one condition can be reused across every signal day of a sweep
    without a caller mutating it mid-run.
    """

    field: str
    operator: str
    value: object = None

    def __post_init__(self) -> None:
        """Reject malformed triples and rewrite collection values as tuples.

        :raises ValueError: for an unregistered operator, a value supplied to
            an operator that takes none, a missing value where one is
            required, a non-collection value where a collection is required,
            or a ``between`` value that is not exactly two items.
        """
        if not isinstance(self.field, str) or not self.field.strip():
            raise ValueError("filter field must be a non-empty string")
        if not isinstance(self.operator, str):
            raise ValueError("filter operator must be a string")

        operator = self.operator
        if operator not in _OPERATORS:
            raise ValueError(
                f"unregistered operator {operator!r}; registered operators are "
                f"{tuple(_OPERATORS)}"
            )
        if operator in _NULL_OPERATORS:
            if self.value is not None:
                raise ValueError(f"operator {operator!r} does not accept a value")
            return
        if self.value is None:
            raise ValueError(
                f"operator {operator!r} requires a value; use 'is_null' or "
                "'not_null' for missing values"
            )
        if operator in _COLLECTION_VALUE_OPERATORS:
            if not _is_collection(self.value):
                raise ValueError(
                    f"operator {operator!r} requires a non-string collection"
                )
            values = tuple(self.value)
            object.__setattr__(self, "value", values)
            if operator == "between" and len(values) != 2:
                raise ValueError("operator 'between' requires exactly two values")


def _coerce_condition(condition: object) -> FilterCondition:
    """Normalise one caller-supplied condition into a FilterCondition.

    Accept a FilterCondition unchanged, or a ``(field, operator, value)`` tuple
    of three items — two where the operator takes no value. Raise ValueError
    for anything else.
    """
    if isinstance(condition, FilterCondition):
        return condition
    if not isinstance(condition, tuple) or len(condition) not in {2, 3}:
        raise ValueError(
            "each filter condition must be FilterCondition or a "
            "(field, operator, value) tuple"
        )
    return FilterCondition(*condition)


def funnel_row(
    condition: str, before: int, after: int, dropped_for_null: int = 0
) -> dict:
    """Build one attrition row in the shared funnel schema.

    Every stage that narrows a population reports through this — filter conditions
    here, scoring attrition in the orchestrator — so a report built from both
    concatenates on identical columns.
    """
    return {
        "condition": condition,
        "before": before,
        "after": after,
        "dropped": before - after,
        "dropped_for_null": dropped_for_null,
    }


def _condition_mask(frame: pd.DataFrame, condition: FilterCondition) -> pd.Series:
    """Build the boolean pass/fail mask for one condition.

    Nulls never pass: a comparison against NaN yields NaN, so the mask is filled
    and every operator but the null pair is ANDed with ``notna()``. An unmeasured
    security is excluded rather than judged.

    :raises KeyError: when the condition names a column the frame lacks.
    """
    if condition.field not in frame.columns:
        raise KeyError(f"filter field {condition.field!r} is not attached to the frame")

    series = frame[condition.field]
    mask = _OPERATORS[condition.operator](series, condition.value)
    mask = pd.Series(mask, index=frame.index).fillna(False).astype(bool)

    if condition.operator not in _NULL_OPERATORS:
        mask &= series.notna()
    return mask


class Filters:
    """An ordered set of conditions a security must satisfy in full.

    Conditions compose as a logical AND, applied one at a time rather than as a
    combined mask. Order affects cost but not the result: a cheap numeric gate
    first leaves fewer rows for an expensive per-row operator.
    """

    def __init__(self, *conditions: FilterCondition | tuple) -> None:
        """Coerce each condition and keep them in the order given.

        :raises ValueError: when no condition is supplied.
        """
        if not conditions:
            raise ValueError("Filters requires at least one condition")
        self.conditions = tuple(
            _coerce_condition(condition) for condition in conditions
        )

    def __repr__(self) -> str:
        """Return the conditions in the order they are applied."""
        return f"Filters({', '.join(str(c) for c in self.conditions)})"

    def _validate_fields(self, frame: pd.DataFrame) -> None:
        """Raise KeyError if any condition names a column ``frame`` lacks.

        Every missing field is reported at once, so a misspelled spec is fixed
        in one pass instead of one error per run.
        """
        missing = sorted(
            {condition.field for condition in self.conditions} - set(frame.columns)
        )
        if missing:
            raise KeyError(
                f"filter fields are not attached to the frame: {missing}. "
                f"Attach them first with attach_signals(frame, signal_day) — "
                f"registered sources are {tuple(SIGNAL_SOURCES)}"
            )

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return the rows of ``frame`` satisfying every condition.

        Original index labels are preserved and ``frame`` itself is not
        modified.
        """
        self._validate_fields(frame)
        survivors = frame
        for condition in self.conditions:
            survivors = survivors[_condition_mask(survivors, condition)]
        return survivors

    def funnel(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return an attrition report for the narrowing ``apply`` performs.

        Counts are marginal: each row reports what its condition removed from the
        survivors of the ones before it. ``dropped_for_null`` separates securities that
        failed the test from those with no value to test — the difference between a
        real gate and a coverage gap.
        """
        self._validate_fields(frame)
        rows = []
        survivors = frame
        for condition in self.conditions:
            before = len(survivors)
            nulls = survivors[condition.field].isna()
            mask = _condition_mask(survivors, condition)
            dropped_for_null = int((nulls & ~mask).sum())
            survivors = survivors[mask]
            after = len(survivors)
            condition_text = f"{condition.field} {condition.operator}"
            if condition.operator not in _NULL_OPERATORS:
                condition_text += f" {condition.value}"
            rows.append(funnel_row(condition_text, before, after, dropped_for_null))
        return pd.DataFrame(rows)


def _empty_facts(repo) -> pd.DataFrame:
    """Build a no-row frame carrying the fact columns ``repo`` declares.

    A signal service returns a bare DataFrame for a date predating its data, which
    would make a filter naming one of its fields raise as though misspelled.
    Preserving the columns gives the honest outcome: every fact null, nothing
    passes, population empty.
    """
    return pd.DataFrame(
        columns=[column for column in repo._COLUMNS if column != "ticker"]
    ).rename_axis("ticker")


def _technical_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    """Assemble ticker-indexed technical facts, stored and derived."""
    frame = TechnicalSignals.get_signals(tickers, signal_day)
    if frame.empty:
        frame = _empty_facts(technical_features_repo)
    frame = TechnicalSignals.attach_return_percentiles(frame)
    frame = TechnicalSignals.attach_market_relative_returns(frame, signal_day)
    return frame


def _fundamental_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    """Assemble ticker-indexed fundamental facts.

    The latest filing published on or before ``signal_day``, plus ratios,
    year-over-year growth, five-year history features, and the signal-day
    repriced valuation ratios from SHARADAR/DAILY.
    """
    frame = FundamentalSignals.get_signals(tickers, signal_day)
    if frame.empty:
        frame = _empty_facts(fundamentals_repo)
    frame = FundamentalSignals.attach_ratios(frame)
    frame = FundamentalSignals.attach_growth(frame, signal_day)
    frame = FundamentalSignals.attach_history_features(frame, signal_day)
    frame = FundamentalSignals.attach_daily_valuation(frame, signal_day)
    return frame


def _event_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    """Assemble ticker-indexed event facts: recency and recent event codes.

    Unlike the other sources this needs no ``_empty_facts`` fallback, because
    ``attach_event_facts`` already emits a row per requested ticker with null
    recencies and an empty code list where nothing happened. Absence of events
    is a fact here rather than missing data.
    """
    frame = EventSignals.get_signals(tickers, signal_day)
    return EventSignals.attach_event_facts(frame, tickers, signal_day)


def _insider_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    """Assemble ticker-indexed insider activity facts.

    Emits a row per requested ticker with zero counts where nothing was filed:
    no disclosed purchase is a fact here, unlike a missing fundamental. Needs no
    ``_empty_facts`` fallback for the same reason.
    """
    frame = InsiderSignals.get_signals(tickers, signal_day)
    frame = InsiderSignals.attach_purchase_classification(frame)
    facts = InsiderSignals.attach_activity_facts(frame, tickers, signal_day)
    return InsiderSignals.attach_marketcap_normalization(facts, signal_day)


def _institutional_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    """Assemble ticker-indexed 13F ownership facts.

    Like the event source it needs no ``_empty_facts`` fallback: it already emits
    a row per requested ticker, null where no institution reported the name.
    """
    frame = InstitutionalSignals.get_signals(tickers, signal_day)
    return InstitutionalSignals.attach_ownership_facts(frame, tickers, signal_day)


SIGNAL_SOURCES = {
    "technical": _technical_facts,
    "fundamental": _fundamental_facts,
    "events": _event_facts,
    "institutional": _institutional_facts,
    "insider": _insider_facts,
}


def attach_signals(
    frame: pd.DataFrame,
    signal_day,
    sources: Iterable[str] = tuple(SIGNAL_SOURCES),
) -> pd.DataFrame:
    """Merge point-in-time facts from the signal layer onto a universe frame.

    ``frame`` must carry a ``ticker`` column. ``sources`` names which chains to
    merge; passing a subset is how a caller skips work it does not need. The signal
    services own what a fact is and how it is made point-in-time.

    :returns: ``frame`` plus every column the requested sources produce, merged
        left so a security missing from a source keeps its row with nulls.
    :raises ValueError: for an unregistered source, or when a source would
        overwrite a column the frame already carries.
    """
    unknown = tuple(name for name in sources if name not in SIGNAL_SOURCES)
    if unknown:
        raise ValueError(
            f"unregistered signal sources {unknown}; registered sources are "
            f"{tuple(SIGNAL_SOURCES)}"
        )

    tickers = frame["ticker"].tolist()
    for name in sources:
        facts = SIGNAL_SOURCES[name](tickers, signal_day)
        overlap = sorted(set(facts.columns) & set(frame.columns))
        if overlap:
            raise ValueError(
                f"signal source {name!r} would overwrite existing columns {overlap}"
            )
        frame = frame.merge(facts, left_on="ticker", right_index=True, how="left")
    return frame
