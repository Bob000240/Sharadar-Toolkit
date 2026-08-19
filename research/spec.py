"""What a screen *is*: the spec type, how to read one, and whether it is sound.

A screen is data, so it can be written outside Python. Each top-level table in
a TOML file is one screen, keyed by the name it is invoked under::

    [deep_value]
    description = "Cheap on several multiples at once."
    filters = [
      ["marketcap", ">=", 2e9],
      ["recent_event_codes", "excludes_any", ["31", "13"]],
    ]

    [deep_value.rank]
    top_n = 25
    metrics = [["pe", "low", 0.5], ["pb", "low", 0.5]]

Filter and metric rows mirror the tuples their Python constructors take, so a
spec reads the same in either form.

Reading and checking are separate passes. ``load`` raises ``SpecError`` for a
file it cannot turn into objects; ``validate`` answers the registry's questions
about a spec that already exists. Running one is ``research.screen``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import research.registry as registry
from research.filters import SCALAR_OPERATORS, Filters
from research.ranking import Ranking
from research.universe import Universe

#: The screens shipped with the toolkit.
CATALOG = Path(__file__).resolve().parent.parent / "strategy.toml"


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


def _value_fits(value: object, expected: type) -> bool:
    """Return whether one filter value is of the type the field compares as."""
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, expected)


def _condition_problems(condition) -> list[str]:
    """Return the operator and value-type problems with one filter condition.

    Both are silent failures rather than errors at run time: a scalar operator
    against a list-valued cell matches nothing, and a mistyped value compares
    false everywhere, so either empties a screen without saying why.
    """
    field = registry.get(condition.field)
    allowed = field.allowed_operators or SCALAR_OPERATORS
    if condition.operator not in allowed:
        message = (
            f"field {condition.field!r} does not accept operator "
            f"{condition.operator!r}; it accepts {tuple(sorted(allowed))}"
        )
        return [message]

    if condition.value is None:
        return []
    values = (
        condition.value if isinstance(condition.value, tuple) else (condition.value,)
    )
    wrong = [v for v in values if not _value_fits(v, field.value_type)]
    if wrong:
        message = (
            f"field {condition.field!r} compares as {field.value_type.__name__}; "
            f"got {wrong[0]!r}"
        )
        return [message]
    return []


def validate(spec: ScreenSpec) -> list[str]:
    """Return every problem with ``spec``, or an empty list when it is sound.

    Checked against the registry alone, with no database and no frame, so a CLI
    or an agent can call it before submitting. Catches unknown field names,
    fields used in a role the registry does not permit, and operators or value
    types the field does not accept.
    """
    problems: list[str] = []

    if spec.filters is not None:
        for condition in spec.filters.conditions:
            if condition.field not in registry.FIELDS:
                problems.append(f"unknown filter field {condition.field!r}")
            elif not registry.get(condition.field).filterable:
                problems.append(f"field {condition.field!r} is not filterable")
            else:
                problems.extend(_condition_problems(condition))

    if spec.rank is not None:
        for metric in spec.rank.metrics:
            if metric.field not in registry.FIELDS:
                problems.append(f"unknown rank field {metric.field!r}")
            elif not registry.get(metric.field).rankable:
                problems.append(f"field {metric.field!r} is not rankable")

    return problems


_SCREEN_KEYS = frozenset({"description", "universe", "filters", "rank"})
_RANK_KEYS = frozenset({"metrics", "group_by", "top_n", "min_coverage"})
_UNIVERSE_KEYS = frozenset(
    {
        "security_types",
        "exchanges",
        "include_tickers",
        "exclude_tickers",
        "recent_trade_days",
    }
)


class SpecError(ValueError):
    """A screen file that cannot be turned into a ``ScreenSpec``."""


def _reject_unknown(where: str, table: dict, allowed: frozenset[str]) -> None:
    """Raise on a key the schema does not define.

    A misspelled key is otherwise silent: ``filterz`` produces a screen with no
    filters that runs happily over the whole universe.
    """
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise SpecError(
            f"{where}: unknown key(s) {unknown}; allowed are {sorted(allowed)}"
        )


def _rows(where: str, value: object, kind: str) -> list[tuple]:
    """Return TOML rows as the tuples the Python constructors accept."""
    if not isinstance(value, list):
        raise SpecError(
            f"{where}: {kind} must be a list of rows, got {type(value).__name__}"
        )
    rows = []
    for index, row in enumerate(value):
        if not isinstance(row, list):
            raise SpecError(f"{where}: {kind}[{index}] must be a row, got {row!r}")
        rows.append(tuple(tuple(v) if isinstance(v, list) else v for v in row))
    return rows


def _universe(where: str, table: dict) -> Universe:
    _reject_unknown(f"{where}.universe", table, _UNIVERSE_KEYS)
    try:
        return Universe(**table)
    except ValueError as exc:
        raise SpecError(f"{where}.universe: {exc}") from exc


def _rank(where: str, table: dict) -> Ranking:
    _reject_unknown(f"{where}.rank", table, _RANK_KEYS)
    if "metrics" not in table:
        raise SpecError(f"{where}.rank: no metrics; omit the table to skip ranking")
    settings = {k: v for k, v in table.items() if k != "metrics"}
    try:
        return Ranking(*_rows(where, table["metrics"], "rank.metrics"), **settings)
    except ValueError as exc:
        raise SpecError(f"{where}.rank: {exc}") from exc


def _screen(name: str, table: dict) -> ScreenSpec:
    """Build one ``ScreenSpec`` from its TOML table."""
    if not isinstance(table, dict):
        raise SpecError(f"{name}: must be a table, got {type(table).__name__}")
    _reject_unknown(name, table, _SCREEN_KEYS)

    filters = None
    if "filters" in table:
        try:
            filters = Filters(*_rows(name, table["filters"], "filters"))
        except ValueError as exc:
            raise SpecError(f"{name}.filters: {exc}") from exc

    return ScreenSpec(
        name=name,
        description=table.get("description", ""),
        universe=_universe(name, table["universe"])
        if "universe" in table
        else Universe(),
        filters=filters,
        rank=_rank(name, table["rank"]) if "rank" in table else None,
    )


def loads(text: str) -> dict[str, ScreenSpec]:
    """Parse TOML text into screens, keyed by name.

    :raises SpecError: for malformed TOML or a screen the schema rejects.
    """
    try:
        tables = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"invalid TOML: {exc}") from exc
    return {name: _screen(name, table) for name, table in tables.items()}


def load(path: str | Path) -> dict[str, ScreenSpec]:
    """Read screens from a TOML file.

    :raises SpecError: when the file is missing, unreadable, or malformed.
    """
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise SpecError(f"cannot read {path}: {exc}") from exc
    try:
        return loads(text)
    except SpecError as exc:
        raise SpecError(f"{path}: {exc}") from exc


def catalog() -> dict[str, ScreenSpec]:
    """Return the shipped screens, keyed by name."""
    return load(CATALOG)
