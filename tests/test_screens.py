import pytest

import research.orchestrator as orchestrator
import research.screens as screens

_SPECS = list(screens.SCREENS.values())
_IDS = list(screens.SCREENS)


# ── the catalog sweep, which must not need a database ────────────────────────


@pytest.mark.parametrize("spec", _SPECS, ids=_IDS)
def test_every_shipped_screen_validates_against_the_registry(spec):
    """The catalog's reason for existing as one collection.

    A field renamed or de-registered in `research.registry` breaks every screen
    that referenced it. Without this, the failure surfaces at a user's next CLI
    run; with it, the rename fails here.
    """
    assert orchestrator.validate(spec) == []


@pytest.mark.parametrize("spec", _SPECS, ids=_IDS)
def test_every_shipped_screen_resolves_its_derive_chains(spec):
    """Every registry source a screen names must be one the loader provides.

    `deep_value` is the case that matters: it is the only shipped screen using
    an event field, so it is the only one exercising the registry's "event" ->
    loader "events" alias.
    """
    assert orchestrator._sources(spec.fields()) != ()


@pytest.mark.parametrize("spec", _SPECS, ids=_IDS)
def test_every_shipped_screen_gates_liquidity(spec):
    """The structural universe enforces no size or turnover floor.

    Without a gate a screen ranks names that cannot be bought, which looks like
    a working result rather than a mistake.
    """
    if spec.filters is None:
        pytest.skip("screen declares no elective filters")
    gated = {"marketcap", "dollar_volume_20d_avg", "close"}
    assert gated & {c.field for c in spec.filters.conditions}


@pytest.mark.parametrize("spec", _SPECS, ids=_IDS)
def test_rank_weights_sum_to_one(spec):
    """A catalog convention, not an engine requirement.

    `Ranking` renormalises by coverage regardless, so this keeps a weight
    readable as a share of the blend rather than guarding correctness.
    """
    if spec.rank is None:
        pytest.skip("screen declares no ranking")
    assert sum(m.weight for m in spec.rank.metrics) == pytest.approx(1.0)


# ── lookup ───────────────────────────────────────────────────────────────────


def test_catalog_keys_match_the_name_on_each_spec():
    """A duplicated constant with an un-renamed `name` would otherwise be
    reachable under one name while reporting another."""
    for name, spec in screens.SCREENS.items():
        assert spec.name == name


def test_get_returns_the_named_screen():
    assert screens.get("deep_value") is screens.DEEP_VALUE


def test_get_names_the_alternatives_when_the_screen_is_unknown():
    with pytest.raises(KeyError, match="unknown screen 'deep_valu'"):
        screens.get("deep_valu")


def test_names_covers_the_whole_catalog():
    assert set(screens.names()) == set(screens.SCREENS)
    assert len(screens.names()) == len(screens.SCREENS)
