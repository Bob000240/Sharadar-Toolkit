import pytest

import pipeline.report as report


def test_a_failed_step_is_recorded_and_the_next_one_still_runs(capsys):
    """The datasets are independent, so one unavailable vendor endpoint must not
    abandon the rest — the whole reason load moved onto this reporter."""
    run = report.Run("update", "all datasets", "2026-08-21")

    with run.step("Equity prices", "fetching") as result:
        result.rows = 12
    with run.step("Fundamentals", "fetching"):
        raise RuntimeError("vendor down")
    with run.step("Events", "fetching") as result:
        result.rows = 3

    failed = run.finish()
    output = capsys.readouterr().out

    assert failed == ["Fundamentals"]
    assert run.completed == 2
    assert "FAILED — RuntimeError: vendor down" in output
    assert "update · 2/3 complete" in output
    assert "1 failed: Fundamentals" in output


def test_a_clean_run_reports_no_failures(capsys):
    run = report.Run("load", "Tickers")
    with run.step("Tickers", "exporting SHARADAR/TICKERS") as result:
        result.rows = 30718

    assert run.finish() == []
    assert "30,718 rows written" in capsys.readouterr().out


def test_a_step_may_replace_the_timing_with_its_own_detail(capsys):
    """A fetch splits its time between the vendor and the database, which is
    what tells you which of the two to go and look at."""
    run = report.Run("update", "Equity prices")
    with run.step("Equity prices", "fetching") as result:
        result.rows = 125_939
        result.note = "(lastupdated_since=2026-08-19)"
        result.detail = "fetch 30.0s · insert 11.5s"
    run.finish()

    output = capsys.readouterr().out
    assert "125,939 rows written (lastupdated_since=2026-08-19)" in output
    assert "[fetch 30.0s · insert 11.5s]" in output


@pytest.mark.parametrize(
    "seconds, expected",
    [(4.13, "4.1s"), (61, "1m 01s"), (2521, "42m 01s"), (7325, "2h 02m")],
)
def test_durations_drop_precision_as_they_grow(seconds, expected):
    assert report._duration(seconds) == expected
