import pytest

import research.screen as screen
import research.spec as spec

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
