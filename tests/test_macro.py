import numpy as np
import pandas as pd

from data.macro_data import (
    MacroData,
    _events_to_daily,
    _first_release_events,
    _yoy_events,
)
from data.signals.sig import Signals
from data.signals.sig_macro import MacroSignals


class FakeFred:
    def get_series(
        self,
        series_id,
        observation_start,
        observation_end,
    ):
        return pd.Series(
            [1.0, 2.0],
            index=pd.to_datetime(["2024-01-31", "2024-03-29"]),
        )

    def get_series_all_releases(
        self,
        series_id,
        realtime_start,
        realtime_end,
    ):
        observation_dates = pd.date_range("2022-12-01", periods=16, freq="MS")
        return pd.DataFrame(
            {
                "date": observation_dates,
                "realtime_start": observation_dates + pd.DateOffset(months=1, days=9),
                "value": np.arange(100.0, 116.0),
            }
        )


def test_first_release_events_discard_later_revisions():
    releases = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-01", "2024-02-01"],
            "realtime_start": ["2024-02-13", "2024-03-12", "2024-03-12"],
            "value": [100.0, 101.0, 110.0],
        }
    )

    events = _first_release_events(releases)

    assert events["value"].tolist() == [100.0, 110.0]
    assert events["available_date"].tolist() == [
        pd.Timestamp("2024-02-13"),
        pd.Timestamp("2024-03-12"),
    ]


def test_release_value_is_not_published_before_available_date():
    events = pd.DataFrame(
        {
            "observation_date": [pd.Timestamp("2024-01-01")],
            "available_date": [pd.Timestamp("2024-02-13")],
            "value": [100.0],
        }
    )
    index = pd.date_range("2024-02-10", "2024-02-15", freq="D")

    values, available_dates = _events_to_daily(events, index)

    assert values.loc["2024-02-12"] != values.loc["2024-02-12"]
    assert values.loc["2024-02-13"] == 100.0
    assert available_dates.loc["2024-02-15"] == pd.Timestamp("2024-02-13")


def test_daily_alignment_carries_last_event_from_before_requested_window():
    events = pd.DataFrame(
        {
            "observation_date": [pd.Timestamp("2024-01-01")],
            "available_date": [pd.Timestamp("2024-02-13")],
            "value": [100.0],
        }
    )
    index = pd.date_range("2024-02-14", "2024-02-15", freq="D")

    values, _ = _events_to_daily(events, index)

    assert values.tolist() == [100.0, 100.0]


def test_yoy_is_calculated_at_observation_frequency():
    observation_dates = pd.date_range("2023-01-01", periods=13, freq="MS")
    events = pd.DataFrame(
        {
            "observation_date": observation_dates,
            "available_date": observation_dates + pd.DateOffset(months=1, days=9),
            "value": np.arange(100.0, 113.0),
        }
    )

    yoy = _yoy_events(events)

    assert len(yoy) == 1
    assert np.isclose(yoy.iloc[0]["value"], 12.0)
    assert yoy.iloc[0]["available_date"] == pd.Timestamp("2024-02-10")


def test_get_macro_assembles_values_and_availability_without_ted():
    result = MacroData(fred=FakeFred()).get_macro("2024-02-01", "2024-03-31")

    assert "ted_spread" not in result
    assert result.loc[result["date"] == "2024-02-09", "cpi"].iloc[0] == 112.0
    assert result.loc[result["date"] == "2024-02-10", "cpi"].iloc[0] == 113.0
    assert result.loc[result["date"] == "2024-02-10", "inflation_as_of"].iloc[
        0
    ] == pd.Timestamp("2024-02-10")
    assert result["cpi_yoy"].notna().all()


def test_macro_get_returns_raw_sql_history(monkeypatch):
    raw = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-07-20"],
            "yield_curve_2_10": [-0.2, 0.3],
        }
    )
    captured = {}

    def fake_get(**kwargs):
        captured.update(kwargs)
        return raw

    monkeypatch.setattr("data.signals.sig_macro.macro_repo.get", fake_get)
    result = MacroSignals.get_signals(pd.Timestamp("2026-07-20"))

    assert issubclass(MacroSignals, Signals)
    assert result.columns.tolist() == ["date", "yield_curve_2_10"]
    assert "yield_curve_change_60d" not in result
    assert captured == {
        "start_date": "2026-01-01",
        "end_date": "2026-07-20",
    }


def test_macro_attachments_preserve_history_and_add_objective_changes():
    dates = pd.date_range("2026-01-01", "2026-07-20", freq="D")
    history = pd.DataFrame(
        {
            "date": dates,
            "yield_curve_2_10": np.linspace(-0.2, 0.3, len(dates)),
            "real_yield_10y": np.linspace(1.0, 1.2, len(dates)),
            "spread_hy": np.linspace(4.0, 3.0, len(dates)),
            "spread_ig": np.linspace(1.0, 0.8, len(dates)),
            "vix": np.linspace(25.0, 15.0, len(dates)),
            "cpi_yoy": np.linspace(3.0, 2.5, len(dates)),
            "claims_as_of": dates,
            "jobless_claims": np.linspace(230_000, 210_000, len(dates)),
        }
    )

    result = MacroSignals.attach_directional_changes(history)
    result = MacroSignals.attach_claims_stats(result)

    assert len(result) == len(history)
    assert result.iloc[-1]["yield_curve_change_60d"] > 0
    assert result.iloc[-1]["spread_hy_change_20d"] < 0
    assert result.iloc[-1]["claims_4w_avg"] > 0
    assert result.iloc[-1]["claims_change_13w_pct"] < 0
