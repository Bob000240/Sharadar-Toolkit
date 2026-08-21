import inspect

import pytest

import database.source.fund_repo as fund_repo
import pipeline.daily_update as daily_update
import pipeline.load_data as load_data
import pipeline.main as main


class _FakeSharadar:
    pass


def test_dataset_resolves_by_name_and_by_sharadar_code():
    assert main.resolve("institutional") == "institutional"
    assert main.resolve("SF3A") == "institutional"
    assert main.resolve("Fund") == "fund"


def test_unknown_dataset_exits_rather_than_running_everything():
    """A typo must not fall through to the whole-pipeline path."""
    with pytest.raises(SystemExit):
        main.resolve("instutional")


def test_load_of_one_dataset_bulk_loads_only_its_table(monkeypatch):
    calls = []
    monkeypatch.setattr(
        load_data, "load_sharadar_table", lambda code: calls.append(code)
    )
    monkeypatch.setattr(load_data, "main", lambda: calls.append("ALL"))

    main.run_load("institutional")

    assert calls == ["SF3A"]


def test_load_of_technicals_computes_them_instead_of_exporting(monkeypatch):
    calls = []
    monkeypatch.setattr(
        load_data, "load_technical_features", lambda: calls.append("computed")
    )
    monkeypatch.setattr(
        load_data,
        "load_sharadar_table",
        lambda code: pytest.fail("technicals have no vendor table"),
    )

    main.run_load("technicals")

    assert calls == ["computed"]


def test_setup_of_one_dataset_recreates_only_its_table(monkeypatch):
    calls = []
    monkeypatch.setattr(fund_repo, "drop_table", lambda: calls.append("drop"))
    monkeypatch.setattr(fund_repo, "create_table", lambda: calls.append("create"))

    main.run_setup("fund")

    assert calls == ["drop", "create"]


def test_every_dataset_has_an_update_step():
    """`update <dataset>` looks its step up by dataset name, so a dataset added
    to one table and not the other raises a KeyError at the user's terminal."""
    assert {step[0] for step in main.UPDATE_STEPS} == set(main.DATASETS)


@pytest.mark.parametrize(
    "step", main.UPDATE_STEPS, ids=[s[0] for s in main.UPDATE_STEPS]
)
def test_client_flag_matches_the_real_function_signature(step):
    """Checked against the real functions, not the fakes the dispatch tests
    patch in: a step whose flag disagrees with its signature is handed a
    SharadarData as its first positional argument, whatever that means there."""
    _, function_name, needs_client = step
    parameters = inspect.signature(getattr(daily_update, function_name)).parameters
    assert needs_client == ("sh" in parameters)


def test_update_of_one_dataset_runs_only_that_step(monkeypatch):
    calls = []
    monkeypatch.setattr(daily_update, "SharadarData", _FakeSharadar)
    monkeypatch.setattr(
        daily_update, "update_institutional", lambda: calls.append("institutional")
    )
    monkeypatch.setattr(
        daily_update,
        "update_equity_prices",
        lambda sh: pytest.fail("only the named step should run"),
    )

    main.run_update("institutional")

    assert calls == ["institutional"]


def test_failed_step_reports_and_exits_nonzero_after_the_rest(monkeypatch):
    calls = []
    monkeypatch.setattr(daily_update, "SharadarData", _FakeSharadar)
    for name in (
        "update_equity_prices",
        "update_fund_prices",
        "update_fundamentals",
        "update_daily_valuation",
        "update_insider",
        "update_events",
        "update_tickers",
    ):
        monkeypatch.setattr(daily_update, name, lambda sh, n=name: calls.append(n))
    monkeypatch.setattr(
        daily_update, "update_technical_features", lambda: calls.append("technicals")
    )

    def _boom():
        raise RuntimeError("vendor down")

    monkeypatch.setattr(daily_update, "update_institutional", _boom)

    with pytest.raises(SystemExit) as exit_info:
        main.run_update(None)

    assert exit_info.value.code == 1
    assert len(calls) == 8
