"""The named screen catalog: the screens this toolkit ships with.

A ``ScreenSpec`` is a judgment about what makes a holding worth owning, kept
out of ``research.orchestrator`` because §5 separates objective facts from
strategy judgments. The orchestrator runs any screen and has no opinion; this
module is the opinions and contains no logic.

Every spec here is data — adding a screen means adding a constant and listing
it in ``_CATALOG``. Conventions, none enforced by the engine: rank weights sum
to 1.0 for readability, every screen carries a liquidity gate, valuation
screens carry a solvency gate, and fields with sparse coverage notes are
avoided so a shipped screen never silently returns nothing.
"""

from __future__ import annotations

from research.filters import Filters
from research.orchestrator import ScreenSpec
from research.ranking import Ranking
from research.universe import Universe

_DISTRESS_EVENT_CODES = ("31", "13", "42", "36", "26")
"""Sharadar 8-K codes for delisting, bankruptcy, restatement, late filing, and
material impairment. Excluded rather than ranked: these are reasons a multiple
is cheap, not evidence that it is a bargain."""


QUALITY_AT_A_PRICE = ScreenSpec(
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

DEEP_VALUE = ScreenSpec(
    name="deep_value",
    description="Cheap on several multiples at once, with solvency and "
    "distress-event floors.",
    filters=Filters(
        ("marketcap", ">=", 2e9),
        ("dollar_volume_20d_avg", ">=", 2e6),
        ("close", ">=", 5),
        ("de", "<=", 2.0),
        ("interest_coverage", ">=", 3.0),
        ("recent_event_codes", "excludes_any", _DISTRESS_EVENT_CODES),
    ),
    rank=Ranking(
        ("pe", "low", 0.30),
        ("evebitda", "low", 0.25),
        ("fcf_yield", "high", 0.25),
        ("pb", "low", 0.20),
        top_n=25,
    ),
)

QUALITY_COMPOUNDERS = ScreenSpec(
    name="quality_compounders",
    description="Durably profitable and still growing, ranked without regard to price.",
    filters=Filters(
        ("marketcap", ">=", 1e9),
        ("dollar_volume_20d_avg", ">=", 3e6),
        ("gross_profitability", ">", 0),
        ("revenue_growth_yoy", ">", 0),
    ),
    rank=Ranking(
        ("gross_profitability", "high", 0.3),
        ("roic", "high", 0.3),
        ("cfo_to_assets", "high", 0.2),
        ("revenue_growth_yoy", "high", 0.2),
        group_by="sector",
        top_n=5,
    ),
)

MOMENTUM_LEADERS = ScreenSpec(
    name="momentum_leaders",
    description="Liquid names in a smooth, established uptrend near their "
    "52-week high.",
    universe=Universe(recent_trade_days=5),
    filters=Filters(
        ("dollar_volume_20d_avg", ">=", 1e7),
        ("close", ">=", 5),
        ("pct_from_sma_200", ">", 0),
        ("pct_from_52w_high", ">=", -15),
        ("return_252d", ">", 0),
    ),
    rank=Ranking(
        ("return_252d", "high", 0.40),
        ("vol_adjusted_momentum", "high", 0.35),
        ("r_squared_60d", "high", 0.25),
        top_n=20,
    ),
)


_CATALOG = (
    QUALITY_AT_A_PRICE,
    DEEP_VALUE,
    QUALITY_COMPOUNDERS,
    MOMENTUM_LEADERS,
)

SCREENS: dict[str, ScreenSpec] = {spec.name: spec for spec in _CATALOG}


def get(name: str) -> ScreenSpec:
    """Return the shipped screen called ``name``.

    :raises KeyError: naming every available screen, which is the error a CLI
        user who mistyped a name should see rather than a bare missing key.
    """
    try:
        return SCREENS[name]
    except KeyError:
        raise KeyError(
            f"unknown screen {name!r}; available screens are {names()}"
        ) from None


def names() -> tuple[str, ...]:
    """Return every shipped screen name, in catalog order."""
    return tuple(SCREENS)


if __name__ == "__main__":
    import research.orchestrator as orchestrator
    import research.registry as registry

    print(f"{len(SCREENS)} shipped screens\n")
    for spec in _CATALOG:
        fields = spec.fields()
        problems = orchestrator.validate(spec)
        filter_count = 0 if spec.filters is None else len(spec.filters.conditions)
        metric_count = 0 if spec.rank is None else len(spec.rank.metrics)
        print(f"{spec.name}")
        print(f"  {spec.description}")
        print(f"  {filter_count} filters, {metric_count} rank metrics")
        print(f"  sources: {sorted(registry.sources(fields))}")
        print(f"  fields:  {', '.join(fields)}")
        print(f"  valid:   {problems or 'yes'}\n")
