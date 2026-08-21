"""The screen command end to end, with the database stubbed out."""

import json

import pandas as pd
import pytest

import pipeline.main as main
import pipeline.present as present
from research.ranking import Ranking
from research.screen import ScreenResult
from research.spec import ScreenSpec


def _result(rows: int = 2, ranked: bool = True) -> ScreenResult:
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"][:rows],
            "sector": ["Technology", "Energy"][:rows],
            "score": [88.4, 71.2][:rows],
            "rank": [1.0, 2.0][:rows],
            "coverage": [1.0, 0.75][:rows],
            "pe": [12.5, 8.1][:rows],
        }
    )
    funnel = pd.DataFrame(
        [
            {
                "condition": "marketcap >= 1000000",
                "before": 100,
                "after": 40,
                "dropped": 60,
                "dropped_for_null": 4,
            }
        ]
    )
    spec = ScreenSpec(
        name="demo",
        description="a demonstration",
        rank=Ranking(("pe", "low")) if ranked else None,
    )
    return ScreenResult(
        signal_day=pd.Timestamp("2026-08-20").date(),
        frame=frame,
        funnel=funnel,
        universe_size=100,
        spec=spec,
    )


def _run_cli(monkeypatch, argv, result=None, catalog=None, align=None):
    """Invoke main() with the screen layer stubbed, returning nothing."""
    import research.calendar as calendar
    import research.screen as screen
    import research.spec as spec_module

    monkeypatch.setattr(
        spec_module, "catalog", lambda: catalog or {"demo": _result().spec}
    )
    monkeypatch.setattr(spec_module, "validate", lambda spec: [])
    monkeypatch.setattr(
        calendar, "latest_session", lambda: pd.Timestamp("2026-08-20").date()
    )
    monkeypatch.setattr(
        calendar, "align", align or (lambda day: pd.Timestamp(day).date())
    )
    stub = _result() if result is None else result
    monkeypatch.setattr(screen, "run", lambda spec, day: stub)
    monkeypatch.setattr("sys.argv", ["pipeline.main", *argv])
    main.main()


def test_screen_prints_session_universe_funnel_and_selections(monkeypatch, capsys):
    """The four things requirement A.10 asks a successful run to show."""
    _run_cli(monkeypatch, ["screen", "demo"])
    out = capsys.readouterr().out

    assert "demo · as of 2026-08-20" in out
    assert "structural universe 100 -> 2 selected" in out
    assert "marketcap >= 1000000" in out
    assert "AAA" in out and "88.4" in out


def test_an_unknown_screen_exits_before_touching_the_database(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run_cli(monkeypatch, ["screen", "nosuch"])

    assert exit_info.value.code != 0
    assert "Unknown screen: nosuch" in str(exit_info.value)


def test_an_unwritable_suffix_is_refused_before_the_run(monkeypatch):
    """Checked up front: a screen can take minutes, and discovering the export
    format is unsupported afterwards throws the work away."""
    with pytest.raises(SystemExit) as exit_info:
        _run_cli(monkeypatch, ["screen", "demo", "--out", "results.txt"])

    assert ".txt" in str(exit_info.value)


def test_a_date_the_calendar_cannot_cover_is_rejected(monkeypatch):
    """Rejected, never moved forward: silently screening a different date than
    the one asked for is the failure point-in-time correctness exists to stop."""

    def refuse(day):
        raise ValueError("1999-01-01 lies outside the loaded calendar")

    with pytest.raises(SystemExit) as exit_info:
        _run_cli(monkeypatch, ["screen", "demo", "--as-of", "1999-01-01"], align=refuse)

    assert "outside the loaded calendar" in str(exit_info.value)


def test_export_writes_csv_and_json(monkeypatch, tmp_path, capsys):
    csv_path = tmp_path / "out.csv"
    _run_cli(monkeypatch, ["screen", "demo", "--out", str(csv_path)])
    assert "AAA" in csv_path.read_text()
    assert "pe" in csv_path.read_text().splitlines()[0]

    json_path = tmp_path / "out.json"
    _run_cli(monkeypatch, ["screen", "demo", "--out", str(json_path)])
    document = json.loads(json_path.read_text())
    assert document["screen"] == "demo"
    assert document["signal_day"] == "2026-08-20"
    assert document["universe_size"] == 100
    assert len(document["selections"]) == 2
    assert capsys.readouterr().out.count("wrote ") == 2


def test_an_empty_result_is_reported_not_raised(monkeypatch, capsys):
    """A valid screen that nothing passes is an answer, not an error."""
    empty = _result(rows=0)
    _run_cli(monkeypatch, ["screen", "demo"], result=empty)

    assert "nothing qualified" in capsys.readouterr().out


def test_the_terminal_view_truncates_and_says_so(capsys):
    result = _result()
    present.present(result, limit=1)
    out = capsys.readouterr().out

    assert "AAA" in out and "BBB" not in out
    assert "1 more, export for the full list" in out
