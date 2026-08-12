from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

import database.source.fundamentals_repo as fundamentals_repo
import database.source.technical_features_repo as technical_features_repo
from data.signals.sig_events import EventSignals
from data.signals.sig_fundamentals import FundamentalSignals
from data.signals.sig_technical import TechnicalSignals


def _between(series: pd.Series, value: object) -> pd.Series:
    lower, upper = value
    return series.between(lower, upper, inclusive="both")


def _in(series: pd.Series, value: object) -> pd.Series:
    return series.isin(value)


def _not_in(series: pd.Series, value: object) -> pd.Series:
    return ~series.isin(value)


def _is_collection(value: object) -> bool:
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


@dataclass(frozen=True)
class FilterCondition:
    """One field/operator/value rule applied to an assembled signal frame."""

    field: str
    operator: str
    value: object = None

    def __post_init__(self) -> None:
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
    if isinstance(condition, FilterCondition):
        return condition
    if not isinstance(condition, tuple) or len(condition) not in {2, 3}:
        raise ValueError(
            "each filter condition must be FilterCondition or a "
            "(field, operator, value) tuple"
        )
    return FilterCondition(*condition)


def _condition_mask(frame: pd.DataFrame, condition: FilterCondition) -> pd.Series:
    if condition.field not in frame.columns:
        raise KeyError(f"filter field {condition.field!r} is not attached to the frame")

    series = frame[condition.field]
    mask = _OPERATORS[condition.operator](series, condition.value)
    mask = pd.Series(mask, index=frame.index).fillna(False).astype(bool)

    if condition.operator not in _NULL_OPERATORS:
        mask &= series.notna()
    return mask


class Filters:
    def __init__(self, *conditions: FilterCondition | tuple) -> None:
        if not conditions:
            raise ValueError("Filters requires at least one condition")
        self.conditions = tuple(
            _coerce_condition(condition) for condition in conditions
        )

    def __repr__(self) -> str:
        return f"Filters({', '.join(str(c) for c in self.conditions)})"

    def _validate_fields(self, frame: pd.DataFrame) -> None:
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
        self._validate_fields(frame)
        survivors = frame
        for condition in self.conditions:
            survivors = survivors[_condition_mask(survivors, condition)]
        return survivors

    def funnel(self, frame: pd.DataFrame) -> pd.DataFrame:
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
            rows.append(
                {
                    "condition": condition_text,
                    "before": before,
                    "after": after,
                    "dropped": before - after,
                    "dropped_for_null": dropped_for_null,
                }
            )
        return pd.DataFrame(rows)


def apply_filter(
    frame: pd.DataFrame,
    field: str,
    operator: str,
    value: object = None,
) -> pd.DataFrame:
    return Filters((field, operator, value)).apply(frame)


def _empty_facts(repo) -> pd.DataFrame:
    """A no-row frame carrying the source's real columns.

    A signal service returns a bare `DataFrame()` with no columns at all when a
    date predates its data. Passing that through would leave the merged frame
    missing every fact, and a filter naming one would raise KeyError as though
    the field were misspelled. Preserving the columns makes the honest outcome
    happen instead: every fact is null, so no security passes a fact-based
    filter, and the population for that date is empty.
    """
    return pd.DataFrame(
        columns=[column for column in repo._COLUMNS if column != "ticker"]
    ).rename_axis("ticker")


def _technical_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    frame = TechnicalSignals.get_signals(tickers, signal_day)
    if frame.empty:
        frame = _empty_facts(technical_features_repo)
    frame = TechnicalSignals.attach_return_percentiles(frame)
    frame = TechnicalSignals.attach_market_relative_returns(frame, signal_day)
    return frame


def _fundamental_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    frame = FundamentalSignals.get_signals(tickers, signal_day)
    if frame.empty:
        frame = _empty_facts(fundamentals_repo)
    frame = FundamentalSignals.attach_ratios(frame)
    frame = FundamentalSignals.attach_growth(frame, signal_day)
    frame = FundamentalSignals.attach_history_features(frame, signal_day)
    return frame


def _event_facts(tickers: list[str], signal_day) -> pd.DataFrame:
    # No _empty_facts fallback: attach_event_facts already emits a row for every
    # requested ticker, with null recencies and an empty code list where nothing
    # happened. Absence of events is a fact here, not missing data.
    return EventSignals.attach_event_facts(tickers, signal_day)


# Every registered source returns one ticker-indexed row per security, so any
# column it produces becomes filterable without this module knowing the names.
# InsiderSignals and InstitutionalSignals are absent on purpose: their
# get_signals return raw transactions and holdings rather than one row per
# ticker, so they need their own attach_* aggregation before they fit here.
SIGNAL_SOURCES = {
    "technical": _technical_facts,
    "fundamental": _fundamental_facts,
    "events": _event_facts,
}


def attach_signals(
    frame: pd.DataFrame,
    signal_day,
    sources: Iterable[str] = tuple(SIGNAL_SOURCES),
) -> pd.DataFrame:
    """Merge point-in-time facts from the signal layer onto a universe frame.

    The signal services own what a fact is and how it is made point-in-time;
    this only joins them on ticker. Filtering then works on any column they
    produce, so adding a field is a signal-layer change rather than an edit
    here.
    """
    unknown = tuple(name for name in sources if name not in SIGNAL_SOURCES)
    if unknown:
        raise ValueError(
            f"unregistered signal sources {unknown}; registered sources are "
            f"{tuple(SIGNAL_SOURCES)}"
        )

    tickers = frame["ticker"].tolist()
    for name in sources:
        # Merged even with no rows: a source that predates its data still
        # carries its columns, so the facts land as nulls and a filter naming
        # one yields an empty population rather than a missing-field KeyError.
        facts = SIGNAL_SOURCES[name](tickers, signal_day)
        overlap = sorted(set(facts.columns) & set(frame.columns))
        if overlap:
            raise ValueError(
                f"signal source {name!r} would overwrite existing columns {overlap}"
            )
        frame = frame.merge(facts, left_on="ticker", right_index=True, how="left")
    return frame


def population(
    universe,
    filters: Filters | None = None,
    sources: Iterable[str] | None = None,
):
    """A ``WalkForward.run(population=...)`` callable for a filtered universe.

    Rebuilds the population per signal day so every fact is point-in-time, then
    applies the filters. ``filters=None`` gives the unfiltered universe, which
    is the baseline any lift measurement is compared against.

    ``sources`` defaults to every registered signal source, so a filter can name
    any fact without the caller also having to declare where it comes from. Pass
    an explicit subset to skip work, or ``()`` for universe columns only. With
    no filters and no explicit request, nothing is attached — the baseline needs
    tickers, not facts.
    """
    if sources is None:
        sources = () if filters is None else tuple(SIGNAL_SOURCES)

    def _population(signal_day):
        frame = universe.run(signal_day)
        if sources:
            frame = attach_signals(frame, signal_day, sources)
        if filters is not None:
            frame = filters.apply(frame)
        return frame.ticker

    return _population


if __name__ == "__main__":
    import data.signals.sig_events as sig_events
    from research.evaluate.forward import ForwardReturns
    from research.evaluate.walk_forward import WalkForward
    from research.universe import Universe

    SIGNAL_DAY = "2024-06-14"
    universe = Universe()
    base = universe.run(SIGNAL_DAY)
    priced = attach_signals(base, SIGNAL_DAY)

    print(f"\nFUNDAMENTALS COVERAGE on {SIGNAL_DAY}")
    print(f"  universe          {len(base):,}")
    print(f"  with marketcap    {priced.marketcap.notna().sum():,}")
    print(f"  null marketcap    {priced.marketcap.isna().sum():,}")

    print(f"\nFUNNEL on {SIGNAL_DAY} — the sector-leader $1B vs $10B question")
    for label, floor in (
        ("alternative: $1B floor", 1_000_000_000),
        ("sector_leaders: $10B floor", 10_000_000_000),
    ):
        print(f"\n  {label}")
        funnel = Filters(("marketcap", ">=", floor)).funnel(priced)
        print(funnel.to_string(index=False))

    SIGNAL_DAYS = pd.date_range("2016-01-01", "2025-01-01", freq="QS").tolist()
    forward = ForwardReturns(horizon_sessions=252)
    walk = WalkForward(universe, forward, benchmark="SPY")

    print(f"\nWALK-FORWARD: does a filter close the gap? ({len(SIGNAL_DAYS)} quarters)")

    # Which codes disqualify is a strategy judgment, not a signal-layer fact:
    # sig_events names the codes but takes no position on them.
    _DISTRESS_CODES = (
        sig_events.BANKRUPTCY_CODE,
        sig_events.DELISTING_CODE,
        sig_events.RESTATEMENT_CODE,
        sig_events.LATE_FILING_CODE,
        sig_events.MATERIAL_IMPAIRMENT_CODE,
    )

    _FILTERS = {
        "no filter (baseline)": None,
        "$1B cap": Filters(("marketcap", ">=", 1e9)),
        "$10B cap": Filters(("marketcap", ">=", 1e10)),
        "profitable": Filters(("netinccmnusd", ">", 0)),
        "liquid >$5M/day": Filters(("dollar_volume_20d_avg", ">=", 5e6)),
        "above SMA200": Filters(("pct_from_sma_200", ">", 0)),
        "no distress events": Filters(
            ("recent_event_codes", "excludes_any", _DISTRESS_CODES)
        ),
        "distress events only": Filters(
            ("recent_event_codes", "contains_any", _DISTRESS_CODES)
        ),
        "$1B + profitable": Filters(("marketcap", ">=", 1e9), ("netinccmnusd", ">", 0)),
        "$1B + profitable + no distress": Filters(
            ("marketcap", ">=", 1e9),
            ("netinccmnusd", ">", 0),
            ("recent_event_codes", "excludes_any", _DISTRESS_CODES),
        ),
        "sector_leaders gates": Filters(
            ("dollar_volume_20d_avg", ">=", 5e6),
            ("marketcap", ">=", 1e10),
            ("netinccmnusd", ">", 0),
            ("return_60d", ">", 0),
            ("return_252d", ">", 0),
            ("pct_from_sma_200", ">", 0),
            ("trend_slope_60d", ">", 0),
        ),
        "sector_leaders + no distress": Filters(
            ("dollar_volume_20d_avg", ">=", 5e6),
            ("marketcap", ">=", 1e10),
            ("netinccmnusd", ">", 0),
            ("return_60d", ">", 0),
            ("return_252d", ">", 0),
            ("pct_from_sma_200", ">", 0),
            ("trend_slope_60d", ">", 0),
            ("recent_event_codes", "excludes_any", _DISTRESS_CODES),
        ),
    }

    results = walk.compare(SIGNAL_DAYS, _FILTERS, additions=attach_signals)
    for label in _FILTERS:
        by_date = results[results.variant == label]
        if by_date.empty:
            continue
        summary = WalkForward.summarize(by_date)
        print(
            f"  {label:<30} measured(median)={by_date.measured.median():>6.0f}   "
            f"mean excess {summary['median_excess']:+.2%}   "
            f"dates beat bench {summary['pct_dates_beat_benchmark']:.1%}"
        )
