"""The evaluate command end to end, with the measurement stubbed out."""

import json
from datetime import date

import pandas as pd
import pytest

import pipeline.main as main
from research.spec import ScreenSpec

_DATES = [date(2024, 1, 2), date(2024, 4, 1), date(2024, 7, 1)]


def _by_date() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_day": _DATES,
            "measured": [33, 31, 30],
            "mean_return": [0.06, -0.036, 0.099],
            "hit_rate": [0.61, 0.36, 0.79],
            "benchmark_return": [0.111, 0.054, 0.048],
            "beat_benchmark_rate": [0.24, 0.24, 0.58],
            "excess_mean": [-0.051, -0.091, 0.051],
            "complete_pct": [1.0, 1.0, 0.97],
        }
    )


def _run_cli(monkeypatch, argv, by_date=None, catalog=None):
    """Invoke main() with the walk-forward stubbed, returning nothing."""
    import research.calendar as calendar
    import research.evaluate.walk_forward as walk_forward
    import research.screen as screen
    import research.spec as spec_module

    specs = catalog or {
        "demo": ScreenSpec(name="demo"),
        "other": ScreenSpec(name="other"),
    }
    monkeypatch.setattr(spec_module, "catalog", lambda: specs)
    monkeypatch.setattr(spec_module, "validate", lambda spec: [])
    monkeypatch.setattr(calendar, "last_session", lambda: date(2026, 8, 20))
    monkeypatch.setattr(calendar, "schedule", lambda *a, **k: _DATES)
    monkeypatch.setattr(screen, "run", lambda spec, day: None)
    frame = _by_date() if by_date is None else by_date
    monkeypatch.setattr(
        walk_forward.WalkForward, "run", lambda self, days, population: frame.copy()
    )
    monkeypatch.setattr("sys.argv", ["pipeline.main", *argv])
    main.main()


def test_evaluate_reports_every_date_and_the_medians(monkeypatch, capsys):
    """The six baseline figures A.9 requires, per date, then summarised."""
    _run_cli(monkeypatch, ["evaluate", "demo"])
    out = capsys.readouterr().out

    assert "63-session horizon vs SPY" in out
    assert "3 dates from 2024-01-02 to 2024-07-01" in out
    for column in ("measured", "mean_return", "hit_rate", "excess_mean"):
        assert column in out
    assert "median_excess" in out


def test_the_absence_of_significance_testing_is_stated_in_the_output(
    monkeypatch, capsys
):
    """A table of excess returns reads as evidence, and this one is not — the
    caveat belongs where the numbers are, not only in the documentation."""
    _run_cli(monkeypatch, ["evaluate", "demo"])
    out = capsys.readouterr().out

    assert "no t-statistic, p-value, or" in out
    assert "not evidence" in out


def test_returns_carry_a_sign_and_rates_do_not(monkeypatch, capsys):
    """`+100%` complete would read as a change rather than a level."""
    _run_cli(monkeypatch, ["evaluate", "demo"])
    out = capsys.readouterr().out

    assert "+6.0%" in out and "-9.1%" in out
    assert "100%" in out and "+100%" not in out


def test_several_screens_are_measured_over_the_same_dates(monkeypatch, capsys):
    _run_cli(monkeypatch, ["evaluate", "demo", "other"])
    out = capsys.readouterr().out

    assert out.count("demo") >= 2 and out.count("other") >= 2
    assert "evaluate · 2/2 complete" in out


def test_a_date_range_with_no_measurement_fails_rather_than_reporting_nothing(
    monkeypatch,
):
    with pytest.raises(SystemExit) as exit_info:
        _run_cli(monkeypatch, ["evaluate", "demo"], by_date=pd.DataFrame())

    assert exit_info.value.code == 1


def test_an_unknown_screen_and_a_bad_suffix_exit_before_measuring(monkeypatch):
    with pytest.raises(SystemExit) as unknown:
        _run_cli(monkeypatch, ["evaluate", "nosuch"])
    assert "Unknown screen: nosuch" in str(unknown.value)

    with pytest.raises(SystemExit) as suffix:
        _run_cli(monkeypatch, ["evaluate", "demo", "--out", "report.txt"])
    assert ".txt" in str(suffix.value)


def test_export_writes_the_per_date_rows(monkeypatch, tmp_path, capsys):
    path = tmp_path / "eval.json"
    _run_cli(monkeypatch, ["evaluate", "demo", "--out", str(path)])

    rows = json.loads(path.read_text())
    assert len(rows) == 3
    assert rows[0]["screen"] == "demo"
    assert rows[0]["signal_day"] == "2024-01-02"
    assert "wrote " in capsys.readouterr().out
