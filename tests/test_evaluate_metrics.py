import numpy as np
import pandas as pd
import pytest

from research.evaluate.metrics import (
    AVG_PAIRWISE_CORRELATION,
    INFORMATION_COEFFICIENT,
    MEDIAN_RETURN,
    MIN_DECILE_OBSERVATIONS,
    MIN_PANEL_SESSIONS,
    MIN_RANK_OBSERVATIONS,
    RETURN_DISPERSION,
    SECTOR_CONCENTRATION,
    TOP_MINUS_BOTTOM_DECILE,
    EvalContext,
    EvalMetric,
)
from research.evaluate.walk_forward import WalkForward


def _measured(n: int, scored: bool = True, inverted: bool = False) -> pd.DataFrame:
    """A measured frame whose score orders returns perfectly, or inversely."""
    returns = np.linspace(-0.2, 0.4, n)
    frame = pd.DataFrame(
        {
            "forward_return": returns,
            "complete": [True] * n,
        }
    )
    if scored:
        frame["score"] = returns[::-1] if inverted else returns
    return frame


# ── the metric type itself ───────────────────────────────────────────────────


def test_metric_rejects_a_blank_name():
    with pytest.raises(ValueError, match="non-empty string"):
        EvalMetric("  ", lambda context: 0.0)


def test_metric_rejects_a_non_callable():
    with pytest.raises(ValueError, match="must be callable"):
        EvalMetric("broken", 42)


# ── rank-quality metrics need a score and enough of it ───────────────────────


def test_information_coefficient_is_one_when_score_orders_returns():
    result = INFORMATION_COEFFICIENT.fn(EvalContext(_measured(50), 0.05))

    assert result == pytest.approx(1.0)


def test_information_coefficient_is_negative_when_the_score_is_inverted():
    result = INFORMATION_COEFFICIENT.fn(EvalContext(_measured(50, inverted=True), 0.05))

    assert result == pytest.approx(-1.0)


def test_information_coefficient_is_null_without_a_score_column():
    """An unscored population is a coverage boundary, not an error: one
    unranked variant in a sweep must not abort the ranked ones."""
    result = INFORMATION_COEFFICIENT.fn(EvalContext(_measured(50, scored=False), 0.05))

    assert pd.isna(result)


def test_information_coefficient_is_null_below_the_observation_floor():
    result = INFORMATION_COEFFICIENT.fn(
        EvalContext(_measured(MIN_RANK_OBSERVATIONS - 1), 0.05)
    )

    assert pd.isna(result)


def test_top_minus_bottom_decile_spreads_the_extremes():
    frame = _measured(MIN_DECILE_OBSERVATIONS)

    result = TOP_MINUS_BOTTOM_DECILE.fn(EvalContext(frame, 0.05))

    size = len(frame) // 10
    expected = (
        frame.nlargest(size, "score").forward_return.mean()
        - frame.nsmallest(size, "score").forward_return.mean()
    )
    assert result == pytest.approx(expected)
    assert result > 0


def test_top_minus_bottom_decile_is_null_below_the_observation_floor():
    result = TOP_MINUS_BOTTOM_DECILE.fn(
        EvalContext(_measured(MIN_DECILE_OBSERVATIONS - 1), 0.05)
    )

    assert pd.isna(result)


# ── distribution metrics need no score ───────────────────────────────────────


def test_median_return_ignores_the_tail_that_carries_the_mean():
    frame = pd.DataFrame(
        {"forward_return": [0.0, 0.0, 0.0, 10.0], "complete": [True] * 4}
    )

    assert MEDIAN_RETURN.fn(EvalContext(frame, 0.0)) == 0.0
    assert frame.forward_return.mean() == 2.5


def test_return_dispersion_reports_population_spread():
    frame = pd.DataFrame({"forward_return": [0.1, 0.3], "complete": [True, True]})

    assert RETURN_DISPERSION.fn(EvalContext(frame, 0.0)) == pytest.approx(0.1)


# ── harness wiring ───────────────────────────────────────────────────────────


def test_metric_names_may_not_shadow_a_baseline_column():
    with pytest.raises(ValueError, match="reserved report columns"):
        WalkForward(
            universe=None,
            forward=None,
            metrics=[EvalMetric("mean_return", lambda context: 0.0)],
        )


def test_metric_names_may_not_repeat():
    metric = EvalMetric("custom", lambda context: 0.0)

    with pytest.raises(ValueError, match="more than once"):
        WalkForward(universe=None, forward=None, metrics=[metric, metric])


def test_summarize_medians_custom_metrics_without_being_told_about_them():
    by_date = pd.DataFrame(
        {
            "signal_day": pd.to_datetime(["2026-01-02", "2026-04-01"]).date,
            "measured": [100, 120],
            "mean_return": [0.10, 0.20],
            "hit_rate": [0.5, 0.6],
            "benchmark_return": [0.05, 0.05],
            "beat_benchmark_rate": [0.5, 0.6],
            "excess_mean": [0.05, 0.15],
            "complete_pct": [1.0, 1.0],
            "information_coefficient": [0.02, 0.06],
        }
    )

    summary = WalkForward.summarize(by_date)

    assert summary["median_information_coefficient"] == pytest.approx(0.04)
    assert summary["median_excess"] == pytest.approx(0.10)


# ── score plumbing: the gap these metrics exist to close ─────────────────────


class _FakeForward:
    """Returns a fixed forward-return frame, so the harness is testable
    without a database."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def run(self, tickers, signal_day) -> pd.DataFrame:
        wanted = list(tickers)
        return self.frame[self.frame.ticker.isin(wanted)].copy()

    def benchmark(self, tickers, signal_day) -> pd.DataFrame:
        return pd.DataFrame({"forward_return": [0.05]})


class _FakeUniverse:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def run(self, signal_day) -> pd.DataFrame:
        return self.frame.copy()


def _forward_frame(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [f"T{i:03d}" for i in range(n)],
            "forward_return": np.linspace(-0.2, 0.4, n),
            "complete": [True] * n,
        }
    )


def test_run_carries_score_from_a_ranked_population_into_the_metrics():
    """The gap this closes: without the score reaching the measured frame, a
    rank-quality metric can only ever report NaN."""
    forward = _forward_frame(50)
    walk = WalkForward(
        universe=_FakeUniverse(forward[["ticker"]]),
        forward=_FakeForward(forward),
        metrics=[INFORMATION_COEFFICIENT],
    )
    scored = forward[["ticker"]].assign(score=forward.forward_return.to_numpy())

    result = walk.run(["2026-01-02"], population=lambda day: scored)

    assert result.loc[0, "information_coefficient"] == pytest.approx(1.0)


def test_run_reports_null_rank_quality_for_an_unscored_population():
    forward = _forward_frame(50)
    walk = WalkForward(
        universe=_FakeUniverse(forward[["ticker"]]),
        forward=_FakeForward(forward),
        metrics=[INFORMATION_COEFFICIENT],
    )

    result = walk.run(["2026-01-02"], population=lambda day: forward.ticker)

    assert pd.isna(result.loc[0, "information_coefficient"])
    # The baseline six are unaffected by a metric that could not resolve.
    assert result.loc[0, "measured"] == 50
    assert result.loc[0, "mean_return"] == pytest.approx(0.1)


def test_compare_scores_each_variant_independently():
    forward = _forward_frame(50)
    universe = forward[["ticker"]]
    walk = WalkForward(
        universe=_FakeUniverse(universe),
        forward=_FakeForward(forward),
        metrics=[INFORMATION_COEFFICIENT],
    )

    class _Ranked:
        def __init__(self, inverted: bool) -> None:
            self.inverted = inverted

        def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
            order = forward.forward_return.to_numpy()
            return frame.assign(score=order[::-1] if self.inverted else order)

    class _Unranked:
        def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
            return frame

    result = walk.compare(
        ["2026-01-02"],
        {"aligned": _Ranked(False), "inverted": _Ranked(True), "plain": _Unranked()},
    )

    by_variant = result.set_index("variant")["information_coefficient"]
    assert by_variant["aligned"] == pytest.approx(1.0)
    assert by_variant["inverted"] == pytest.approx(-1.0)
    assert pd.isna(by_variant["plain"])


# ── concentration: is the population many bets or one repeated? ──────────────


def _panel(n_tickers: int, n_sessions: int, common: float) -> pd.DataFrame:
    """A return panel where ``common`` mixes a shared factor into independent
    noise: 0.0 gives uncorrelated names, 1.0 gives identical ones."""
    rng = np.random.default_rng(0)
    factor = rng.normal(size=n_sessions)
    idiosyncratic = rng.normal(size=(n_sessions, n_tickers))
    returns = common * factor[:, None] + (1 - common) * idiosyncratic
    return pd.DataFrame(
        returns,
        index=pd.date_range("2026-01-05", periods=n_sessions, freq="B"),
        columns=[f"T{i:03d}" for i in range(n_tickers)],
    )


def test_avg_pairwise_correlation_is_near_one_when_names_move_together():
    context = EvalContext(_measured(10), 0.05, panel=_panel(10, 120, common=1.0))

    assert AVG_PAIRWISE_CORRELATION.fn(context) == pytest.approx(1.0)


def test_avg_pairwise_correlation_is_near_zero_for_independent_names():
    context = EvalContext(_measured(10), 0.05, panel=_panel(10, 250, common=0.0))

    assert AVG_PAIRWISE_CORRELATION.fn(context) == pytest.approx(0.0, abs=0.15)


def test_avg_pairwise_correlation_separates_a_concentrated_population():
    """The distinction the metric exists for: two populations can post the same
    dispersion while one is a single bet held many times."""
    diversified = AVG_PAIRWISE_CORRELATION.fn(
        EvalContext(_measured(20), 0.05, panel=_panel(20, 250, common=0.0))
    )
    concentrated = AVG_PAIRWISE_CORRELATION.fn(
        EvalContext(_measured(20), 0.05, panel=_panel(20, 250, common=0.8))
    )

    assert concentrated > diversified + 0.5


def test_avg_pairwise_correlation_is_null_without_a_panel():
    """A metric that declares needs_panel still sees None when the harness was
    not asked for one, and must not raise."""
    assert pd.isna(AVG_PAIRWISE_CORRELATION.fn(EvalContext(_measured(20), 0.05)))


def test_avg_pairwise_correlation_is_null_below_the_session_floor():
    context = EvalContext(
        _measured(10), 0.05, panel=_panel(10, MIN_PANEL_SESSIONS - 1, common=1.0)
    )

    assert pd.isna(AVG_PAIRWISE_CORRELATION.fn(context))


def test_sector_concentration_is_one_when_every_name_shares_a_sector():
    frame = _measured(8).assign(sector="Technology")

    assert SECTOR_CONCENTRATION.fn(EvalContext(frame, 0.05)) == pytest.approx(1.0)


def test_sector_concentration_reciprocal_reads_as_effective_sector_count():
    frame = _measured(8).assign(sector=["A", "B", "C", "D"] * 2)

    result = SECTOR_CONCENTRATION.fn(EvalContext(frame, 0.05))

    assert result == pytest.approx(0.25)
    assert 1 / result == pytest.approx(4.0)


def test_sector_concentration_is_null_without_a_sector_column():
    assert pd.isna(SECTOR_CONCENTRATION.fn(EvalContext(_measured(8), 0.05)))


# ── the panel is paid for only when something reads it ───────────────────────


class _CountingForward(_FakeForward):
    """Records panel fetches, so the harness's laziness is testable."""

    def __init__(self, frame: pd.DataFrame, panel: pd.DataFrame) -> None:
        super().__init__(frame)
        self._panel = panel
        self.panel_calls = 0

    def panel(self, tickers, signal_day) -> pd.DataFrame:
        self.panel_calls += 1
        held = [t for t in tickers if t in self._panel.columns]
        return self._panel[held]


def test_panel_is_not_fetched_when_no_metric_needs_it():
    forward = _forward_frame(20)
    counting = _CountingForward(forward, _panel(20, 120, common=0.5))
    walk = WalkForward(
        universe=_FakeUniverse(forward[["ticker"]]),
        forward=counting,
        metrics=[MEDIAN_RETURN],
    )

    walk.run(["2026-01-02"], population=lambda day: forward.ticker)

    assert walk.needs_panel is False
    assert counting.panel_calls == 0


def test_panel_is_fetched_once_per_date_when_a_metric_needs_it():
    forward = _forward_frame(20)
    panel = _panel(20, 120, common=1.0)
    panel.columns = forward.ticker.tolist()
    counting = _CountingForward(forward, panel)
    walk = WalkForward(
        universe=_FakeUniverse(forward[["ticker"]]),
        forward=counting,
        metrics=[AVG_PAIRWISE_CORRELATION],
    )

    result = walk.run(["2026-01-02"], population=lambda day: forward.ticker)

    assert walk.needs_panel is True
    assert counting.panel_calls == 1
    assert result.loc[0, "avg_pairwise_correlation"] == pytest.approx(1.0)


def test_compare_fetches_one_panel_per_date_not_one_per_variant():
    """Three variants, one query: the panel is the expensive part and every
    variant draws from the same window."""
    forward = _forward_frame(20)
    panel = _panel(20, 120, common=1.0)
    panel.columns = forward.ticker.tolist()
    counting = _CountingForward(forward, panel)
    walk = WalkForward(
        universe=_FakeUniverse(forward[["ticker"]]),
        forward=counting,
        metrics=[AVG_PAIRWISE_CORRELATION],
    )

    class _Half:
        def apply(self, frame):
            return frame.head(len(frame) // 2)

    class _All:
        def apply(self, frame):
            return frame

    result = walk.compare(
        ["2026-01-02"], {"half": _Half(), "all": _All(), "plain": None}
    )

    assert counting.panel_calls == 1
    assert len(result) == 3
    assert result["avg_pairwise_correlation"].notna().all()


def test_sector_carries_from_the_selection_into_the_metric():
    forward = _forward_frame(8)
    walk = WalkForward(
        universe=_FakeUniverse(forward[["ticker"]]),
        forward=_FakeForward(forward),
        metrics=[SECTOR_CONCENTRATION],
    )
    selected = forward[["ticker"]].assign(sector=["A", "B", "C", "D"] * 2)

    result = walk.run(["2026-01-02"], population=lambda day: selected)

    assert result.loc[0, "sector_concentration"] == pytest.approx(0.25)
