from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

import database.source.fundamentals_repo as fundamentals_repo
import database.source.technical_features_repo as technical_features_repo
from research.signals.sig_events import EventSignals
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


def _empty_facts(repo) -> pd.DataFrame:
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
    return EventSignals.attach_event_facts(tickers, signal_day)


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
