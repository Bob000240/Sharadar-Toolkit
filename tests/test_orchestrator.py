import pandas as pd
import pytest

import research.calendar as calendar
import research.orchestrator as orchestrator
from research.filters import Filters
from research.ranking import Ranking
from research.signals.sig import Signals

_SIGNAL_DAY = "2024-01-05"


class _FakeUniverse:
    """Stands in for Universe.run without a database."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list = []

    def run(self, signal_day) -> pd.DataFrame:
        self.calls.append(signal_day)
        return self.frame.copy()


def _universe_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "DDD"],
            "currency": ["USD"] * 4,
        }
    )


def _signal_facts() -> pd.DataFrame:
    """Indexed by ticker, the shape attach_signals merges on.

    DDD is the loss-maker: a negative `pe` must be masked out of the percentile
    rather than ranked as the cheapest name.
    """
    return pd.DataFrame(
        {
            "marketcap": [50e9, 30e9, 20e9, 40e9],
            "roic": [0.30, 0.20, 0.10, 0.25],
            "pe": [10.0, 20.0, 30.0, -5.0],
        },
        index=pd.Index(["AAA", "BBB", "CCC", "DDD"], name="ticker"),
    )


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.setattr(
        calendar, "_sessions", pd.DatetimeIndex(pd.to_datetime([_SIGNAL_DAY]))
    )
    monkeypatch.setattr(
        orchestrator,
        "attach_signals",
        lambda frame, day, sources: frame.merge(
            _signal_facts(), left_on="ticker", right_index=True, how="left"
        ),
    )
    monkeypatch.setattr(
        Signals,
        "attach_sectors",
        staticmethod(lambda frame: frame.assign(sector="Technology")),
    )


def _spec(**kwargs) -> orchestrator.ScreenSpec:
    kwargs.setdefault("universe", _FakeUniverse(_universe_frame()))
    return orchestrator.ScreenSpec(**kwargs)


# ── validation, which must not need a database ───────────────────────────────


def test_validate_rejects_an_unregistered_filter_field():
    spec = _spec(filters=Filters(("marketcapp", ">=", 1e10)))
    assert orchestrator.validate(spec) == ["unknown filter field 'marketcapp'"]


def test_validate_rejects_an_unregistered_rank_field():
    spec = _spec(rank=Ranking(("roicc", "high")))
    assert orchestrator.validate(spec) == ["unknown rank field 'roicc'"]


def test_validate_rejects_ranking_on_a_filter_only_field():
    """recent_event_codes is registered but rankable=False."""
    spec = _spec(rank=Ranking(("recent_event_codes", "high")))
    assert orchestrator.validate(spec) == ["field 'recent_event_codes' is not rankable"]


def test_validate_passes_a_well_formed_spec():
    spec = _spec(
        filters=Filters(("marketcap", ">=", 1e10)), rank=Ranking(("roic", "high"))
    )
    assert orchestrator.validate(spec) == []


def test_run_refuses_an_invalid_spec_before_touching_the_universe():
    universe = _FakeUniverse(_universe_frame())
    spec = _spec(universe=universe, filters=Filters(("nonsense", ">", 1)))
    with pytest.raises(ValueError, match="invalid ScreenSpec"):
        orchestrator.run(spec, _SIGNAL_DAY)
    assert universe.calls == []  # never queried


# ── field and source resolution ──────────────────────────────────────────────


def test_spec_fields_collects_filter_and_rank_fields_without_duplicates():
    spec = _spec(
        filters=Filters(("marketcap", ">=", 1e10), ("roic", ">", 0)),
        rank=Ranking(("roic", "high"), ("pe", "low")),
    )
    assert spec.fields() == ("marketcap", "roic", "pe")


def test_sources_requests_only_the_chains_the_spec_references():
    assert orchestrator._sources(("roic", "pe")) == ("fundamental",)
    assert orchestrator._sources(("return_252d",)) == ("technical",)


def test_sources_maps_the_registry_event_alias_onto_the_loader_name():
    """The registry says 'event'; SIGNAL_SOURCES registers 'events'."""
    assert orchestrator._sources(("recent_event_codes",)) == ("events",)


# ── the order-of-operations decision ─────────────────────────────────────────


def test_signal_day_is_aligned_onto_a_real_session():
    universe = _FakeUniverse(_universe_frame())
    spec = _spec(universe=universe, filters=Filters(("marketcap", ">=", 1e9)))
    result = orchestrator.run(spec, "2024-01-06")  # a Saturday
    assert result.signal_day == pd.Timestamp(_SIGNAL_DAY).date()
    assert universe.calls == [pd.Timestamp(_SIGNAL_DAY).date()]


def test_scores_are_computed_before_elective_filters():
    """The load-bearing choice: a name's score must not depend on which filters
    the spec happened to include."""
    ranking = Ranking(("roic", "high"))
    wide = orchestrator.run(_spec(rank=ranking), _SIGNAL_DAY)
    narrow = orchestrator.run(
        _spec(filters=Filters(("marketcap", ">=", 35e9)), rank=ranking), _SIGNAL_DAY
    )
    assert set(narrow.frame["ticker"]) == {"AAA", "DDD"}
    for ticker in narrow.frame["ticker"]:
        assert narrow.frame.set_index("ticker").loc[ticker, "score"] == pytest.approx(
            wide.frame.set_index("ticker").loc[ticker, "score"]
        )


def test_rank_is_recomputed_over_the_survivors_not_inherited():
    """Scores are universe-relative; ranks are candidate-relative. AAA is 1st
    either way, but DDD must become 2nd rather than keeping its universe rank."""
    result = orchestrator.run(
        _spec(
            filters=Filters(("marketcap", ">=", 35e9)),
            rank=Ranking(("roic", "high")),
        ),
        _SIGNAL_DAY,
    )
    ranks = result.frame.set_index("ticker")["rank"]
    assert ranks["AAA"] == 1
    assert ranks["DDD"] == 2


def test_top_n_is_applied_after_filtering():
    result = orchestrator.run(
        _spec(
            filters=Filters(("marketcap", ">=", 20e9)),
            rank=Ranking(("roic", "high"), top_n=2),
        ),
        _SIGNAL_DAY,
    )
    assert len(result) == 2
    assert list(result.frame["ticker"]) == ["AAA", "DDD"]


# ── registry-driven behaviour ────────────────────────────────────────────────


def test_positive_only_masking_comes_from_the_registry():
    """`pe` is registered positive_only, so DDD's negative PE is undefined, not
    'cheapest'. Without masking DDD would score top on a low-pe ranking."""
    result = orchestrator.run(_spec(rank=Ranking(("pe", "low"))), _SIGNAL_DAY)
    scored = result.frame.set_index("ticker")
    assert "DDD" not in scored.index
    assert scored.index[0] == "AAA"  # cheapest among the positive multiples


# ── result reporting ─────────────────────────────────────────────────────────


def test_result_reports_the_structural_universe_size():
    result = orchestrator.run(
        _spec(filters=Filters(("marketcap", ">=", 35e9))), _SIGNAL_DAY
    )
    assert result.universe_size == 4
    assert len(result) == 2


def test_funnel_accounts_for_scoring_attrition_so_counts_reconcile():
    """The first funnel row must start at the structural universe size, not at
    whatever survived scoring."""
    result = orchestrator.run(
        _spec(
            filters=Filters(("marketcap", ">=", 35e9)),
            rank=Ranking(("pe", "low")),
        ),
        _SIGNAL_DAY,
    )
    assert result.funnel.iloc[0]["before"] == result.universe_size
    assert result.funnel.iloc[0]["dropped"] == 1  # DDD, unscoreable on pe


def test_a_spec_without_a_rank_filters_without_scoring():
    result = orchestrator.run(
        _spec(filters=Filters(("marketcap", ">=", 35e9))), _SIGNAL_DAY
    )
    assert "score" not in result.frame.columns
    assert set(result.frame["ticker"]) == {"AAA", "DDD"}


def test_an_empty_universe_returns_an_empty_result_rather_than_raising():
    spec = _spec(
        universe=_FakeUniverse(_universe_frame().iloc[:0]),
        filters=Filters(("marketcap", ">=", 1e9)),
    )
    result = orchestrator.run(spec, _SIGNAL_DAY)
    assert len(result) == 0
    assert result.universe_size == 0
