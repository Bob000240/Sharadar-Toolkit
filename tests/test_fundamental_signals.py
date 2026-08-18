import numpy as np
import pandas as pd
import pytest

from research.signals.sig import Signals
from research.signals.sig_fundamentals import FundamentalSignals


def test_fundamental_signals_inherits_common_helpers():
    numerator = pd.Series([20.0, -5.0, 10.0, 10.0])
    denominator = pd.Series([100.0, 100.0, 0.0, np.nan])

    result = FundamentalSignals.positive_ratio(numerator, denominator)

    assert issubclass(FundamentalSignals, Signals)
    assert result.iloc[0] == 0.2
    assert result.iloc[1:].isna().all()


def test_sector_rank_stays_sector_relative_for_small_peer_groups():
    values = pd.Series([1.0, 2.0, 10.0, 20.0])
    sectors = pd.Series(["A", "A", "B", "B"])

    result = FundamentalSignals.rank_within_sector(values, sectors)

    assert result.tolist() == [50.0, 100.0, 50.0, 100.0]


def test_get_signals_returns_only_requested_art_rows(monkeypatch):
    monkeypatch.setattr(
        "research.signals.sig_fundamentals.fundamentals_repo.get_latest_rows",
        lambda tickers, dimension, signal_day: pd.DataFrame(
            {
                "ticker": ["BBB", "AAA"],
                "datekey": pd.to_datetime(["2026-06-01", "2026-06-01"]),
                "marketcap": [200.0, 100.0],
            }
        ),
    )

    result = FundamentalSignals.get_signals(
        ["AAA", "BBB"],
        pd.Timestamp("2026-07-18"),
    )

    assert result.index.tolist() == ["AAA", "BBB"]
    assert result.loc["AAA", "marketcap"] == 100.0
    assert "sector" not in result
    assert "fcf_yield" not in result
    assert "revenue_growth_yoy" not in result


def test_attach_history_features_uses_five_year_annual_history(monkeypatch):
    rows = []
    for offset, year in enumerate(range(2019, 2025)):
        rows.append(
            {
                "ticker": "TEST",
                "calendardate": pd.Timestamp(year, 12, 31),
                "datekey": pd.Timestamp(year + 1, 2, 15),
                "gp": 30 + offset * 2,
                "assets": 100,
                "ncfo": 20 + offset * 2,
                "shareswa": 100 - offset * 4,
                "de": 0.8 - offset * 0.08,
                "roe": 0.10 + offset * 0.01,
                "roa": 0.05 + offset * 0.01,
                "roic": 0.07 + offset * 0.01,
                "grossmargin": 0.30 + offset * 0.02,
            }
        )
    monkeypatch.setattr(
        "research.signals.sig_fundamentals.fundamentals_repo.get",
        lambda **kwargs: pd.DataFrame(rows),
    )

    result = FundamentalSignals.attach_history_features(
        pd.DataFrame({"sql_value": [1]}, index=["TEST"]),
        pd.Timestamp("2026-07-18"),
    )

    assert result.loc["TEST", "sql_value"] == 1
    assert result.loc["TEST", "complete_multi_year_history"]
    assert result.loc["TEST", "quality_history_observations"] == 6
    assert result.loc["TEST", "gross_profitability_change_5y"] == pytest.approx(0.1)
    assert result.loc["TEST", "share_dilution_5y"] == pytest.approx(-0.2)


def test_attach_ratios_preserves_sql_and_history_columns():
    frame = pd.DataFrame(
        {
            "sql_value": [7],
            "roa_change_5y": [0.05],
            "fcf": [20.0],
            "marketcap": [100.0],
            "ebit": [30.0],
            "intexp": [5.0],
            "gp": [40.0],
            "assets": [200.0],
            "ncfo": [25.0],
            "netinc": [20.0],
            "ncfcommon": [-4.0],
            "ncfdiv": [-1.0],
        },
        index=["TEST"],
    )

    result = FundamentalSignals.attach_ratios(frame)

    assert result.loc["TEST", "sql_value"] == 7
    assert result.loc["TEST", "roa_change_5y"] == 0.05
    assert result.loc["TEST", "fcf_yield"] == 0.2
    assert result.loc["TEST", "interest_coverage"] == 6.0
    assert result.loc["TEST", "gross_profitability"] == 0.2
    assert result.loc["TEST", "cfo_to_assets"] == 0.125
    assert result.loc["TEST", "accruals"] == -0.025
    assert result.loc["TEST", "net_payout_yield"] == 0.05


def test_attach_sector_ranks_adds_direction_free_percentiles():
    index = [f"T{i}" for i in range(10)]
    frame = pd.DataFrame(
        {
            "sector": ["Technology"] * 10,
            "pe": range(1, 11),
            "roe": range(10, 0, -1),
        },
        index=index,
    )

    result = FundamentalSignals.attach_sector_ranks(frame, ["pe", "roe", "fcf_yield"])

    assert result.loc["T0", "pe_sector_pct"] == 10.0
    assert result.loc["T9", "pe_sector_pct"] == 100.0
    assert result.loc["T0", "roe_sector_pct"] == 100.0
    assert result["fcf_yield_sector_pct"].isna().all()


def _daily_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "date": pd.to_datetime(["2026-08-14"] * 2),
            "lastupdated": pd.to_datetime(["2026-08-14"] * 2),
            "ev": [12_000.0, 500.0],
            "evebit": [15.0, 8.0],
            "evebitda": [12.0, 6.0],
            "marketcap": [10_000.0, 400.0],
            "pb": [3.0, 1.2],
            "pe": [25.0, -4.0],
            "ps": [5.0, 0.8],
        }
    )


@pytest.fixture
def stub_daily_repo(monkeypatch):
    monkeypatch.setattr(
        "research.signals.sig_fundamentals.daily_repo.get_latest_rows",
        lambda tickers, signal_day: _daily_rows(),
    )


def test_attach_daily_valuation_suffixes_and_keeps_sf1_columns(stub_daily_repo):
    frame = pd.DataFrame(
        {"pe": [30.0], "marketcap": [9e9]},
        index=pd.Index(["AAA"], name="ticker"),
    )

    result = FundamentalSignals.attach_daily_valuation(
        frame, pd.Timestamp("2026-08-14")
    )

    # The SF1 columns survive untouched; the DAILY twins arrive suffixed.
    assert result.loc["AAA", "pe"] == 30.0
    assert result.loc["AAA", "pe_daily"] == 25.0
    assert "date" not in result.columns
    assert "lastupdated" not in result.columns


def test_attach_daily_valuation_normalizes_vendor_millions(stub_daily_repo):
    frame = pd.DataFrame(index=pd.Index(["AAA"], name="ticker"))

    result = FundamentalSignals.attach_daily_valuation(
        frame, pd.Timestamp("2026-08-14")
    )

    assert result.loc["AAA", "marketcap_daily"] == 10_000.0 * 1e6
    assert result.loc["AAA", "ev_daily"] == 12_000.0 * 1e6


def test_attach_daily_valuation_keeps_uncovered_tickers_with_nulls(stub_daily_repo):
    frame = pd.DataFrame(index=pd.Index(["AAA", "ZZZ"], name="ticker"))

    result = FundamentalSignals.attach_daily_valuation(
        frame, pd.Timestamp("2026-08-14")
    )

    assert list(result.index) == ["AAA", "ZZZ"]
    assert pd.isna(result.loc["ZZZ", "pe_daily"])


def test_attach_daily_valuation_empty_table_still_adds_the_columns(monkeypatch):
    monkeypatch.setattr(
        "research.signals.sig_fundamentals.daily_repo.get_latest_rows",
        lambda tickers, signal_day: pd.DataFrame(),
    )
    frame = pd.DataFrame(index=pd.Index(["AAA"], name="ticker"))

    result = FundamentalSignals.attach_daily_valuation(
        frame, pd.Timestamp("2026-08-14")
    )

    assert "pe_daily" in result.columns
    assert "marketcap_daily" in result.columns
    assert result["pe_daily"].isna().all()
