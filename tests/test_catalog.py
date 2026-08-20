import pytest

import research.filters as filters
import research.registry as registry
import research.screen as screen
import research.spec as spec
from research.signals.sig_events import EVENT_FACT_COLUMNS
from research.signals.sig_insider import ACTIVITY_FACT_COLUMNS, MARKETCAP_FACT_COLUMN
from research.signals.sig_institutional import (
    OWNERSHIP_FACT_COLUMNS,
    PROVENANCE_COLUMNS,
)

_CATALOG = spec.catalog()
_SPECS = list(_CATALOG.values())
_IDS = list(_CATALOG)


# ── the catalog sweep, which must not need a database ────────────────────────


@pytest.mark.parametrize("shipped", _SPECS, ids=_IDS)
def test_every_shipped_screen_validates_against_the_registry(shipped):
    """The catalog's reason for existing as one collection.

    A field renamed or de-registered in `research.registry` breaks every screen
    that referenced it. Without this, the failure surfaces at a user's next CLI
    run; with it, the rename fails here.
    """
    assert spec.validate(shipped) == []


@pytest.mark.parametrize("shipped", _SPECS, ids=_IDS)
def test_every_shipped_screen_resolves_its_derive_chains(shipped):
    """`deep_value` is the case that matters: it is the only shipped screen
    using an event field, so it alone exercises the registry's "event" ->
    loader "events" alias."""
    assert screen._sources(shipped.fields()) != ()


@pytest.mark.parametrize("shipped", _SPECS, ids=_IDS)
def test_every_shipped_screen_gates_liquidity(shipped):
    """The structural universe enforces no size or turnover floor, so without a
    gate a screen ranks names that cannot be bought."""
    if shipped.filters is None:
        pytest.skip("screen declares no elective filters")
    gated = {"marketcap", "dollar_volume_20d_avg", "close"}
    assert gated & {c.field for c in shipped.filters.conditions}


@pytest.mark.parametrize("shipped", _SPECS, ids=_IDS)
def test_rank_weights_sum_to_one(shipped):
    """A catalog convention, not an engine requirement: `Ranking` renormalises
    by coverage regardless, so this keeps a weight readable as a share."""
    if shipped.rank is None:
        pytest.skip("screen declares no ranking")
    assert sum(m.weight for m in shipped.rank.metrics) == pytest.approx(1.0)


# ── the file itself ──────────────────────────────────────────────────────────


def test_the_catalog_is_a_toml_file_beside_the_package():
    """Screens are data: one can be added without editing Python."""
    assert spec.CATALOG.name == "strategy.toml"
    assert spec.CATALOG.exists()


def test_catalog_keys_match_the_name_on_each_spec():
    """A table renamed without its spec would otherwise be reachable under one
    name while reporting another."""
    for name, shipped in _CATALOG.items():
        assert shipped.name == name


def test_the_catalog_ships_more_than_one_screen():
    assert len(_CATALOG) > 1


# ── the registry against the signal loader ───────────────────────────────────


@pytest.mark.parametrize("key", sorted(registry.FIELDS))
def test_every_registered_field_resolves_to_a_signal_loader(key):
    """A field whose source has no loader raises only when a screen names it.

    The registry says "event" where the loader says "events"; any future source
    added on one side alone fails here instead of at a user's next run.
    """
    assert screen._sources((key,))[0] in filters.SIGNAL_SOURCES


@pytest.mark.parametrize(
    "key", sorted(k for k, f in registry.FIELDS.items() if f.source == "insider")
)
def test_insider_fields_select_rather_than_rank(key):
    """Only ~7% of traded names carry an insider purchase in 30 days, so a
    percentile over the structural universe is a tie block at zero, and a blend
    containing one would be decided by the tie-break rather than by the fact."""
    assert not registry.get(key).rankable


# ── the registry against what the sources actually emit ──────────────────────

_EMITTED_FACTS = {
    "event": (frozenset(EVENT_FACT_COLUMNS), frozenset()),
    "insider": (
        frozenset(ACTIVITY_FACT_COLUMNS) | {MARKETCAP_FACT_COLUMN},
        frozenset(),
    ),
    "institutional": (
        frozenset(OWNERSHIP_FACT_COLUMNS),
        frozenset(PROVENANCE_COLUMNS),
    ),
}


@pytest.mark.parametrize("source", sorted(_EMITTED_FACTS))
def test_every_emitted_fact_is_registered_or_declared_provenance(source):
    """A fact reaching the frame without a registry entry is invisible to the
    CLI and to a GUI, and silently unscreenable; the only ones allowed to stay
    unregistered are the provenance columns each source declares."""
    emitted, provenance = _EMITTED_FACTS[source]
    registered = {key for key, f in registry.FIELDS.items() if f.source == source}
    assert emitted - registered == provenance


@pytest.mark.parametrize("source", sorted(_EMITTED_FACTS))
def test_no_registered_field_outlives_the_fact_behind_it(source):
    """The other direction: a registered field its source stopped emitting
    passes validation and then raises a KeyError against the assembled frame."""
    emitted, _ = _EMITTED_FACTS[source]
    registered = {key for key, f in registry.FIELDS.items() if f.source == source}
    assert registered - emitted == set()
