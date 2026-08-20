import numpy as np
import pandas as pd
import pytest

from research.signals.sig import Signals
from research.signals.sig_events import EventSignals
from research.signals.sig_insider import InsiderSignals
from research.signals.sig_institutional import InstitutionalSignals


def _purchase(
    owner: str | None,
    transaction_date: str | None,
    filing_date: str,
    *,
    ticker: str = "TEST",
    code: str = "P",
    value: float = 100_000,
    shares: float = 10,
    post_holdings: float = 100,
    officer: str = "N",
    director: str = "N",
) -> dict:
    return {
        "ticker": ticker,
        "transactioncode": code,
        "ownername": owner,
        "transactiondate": transaction_date,
        "filingdate": filing_date,
        "transactionvalue": value,
        "transactionshares": shares,
        "sharesownedfollowingtransaction": post_holdings,
        "isofficer": officer,
        "isdirector": director,
    }


def test_remaining_signal_services_inherit_common_helpers():
    assert issubclass(EventSignals, Signals)
    assert issubclass(InsiderSignals, Signals)
    assert issubclass(InstitutionalSignals, Signals)


def test_event_facts_fetch_window_and_aggregation(monkeypatch):
    captured = {}

    def fake_get(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            {
                "ticker": ["AAA", "AAA"],
                "date": ["2026-07-15", "2026-07-18"],
                "eventcodes": ["35", "22|42"],
            }
        )

    monkeypatch.setattr("research.signals.sig_events.event_repo.get", fake_get)
    frame = EventSignals.get_signals(["AAA", "NO_EVENTS"], pd.Timestamp("2026-07-20"))
    facts = EventSignals.attach_event_facts(
        frame,
        ["AAA", "NO_EVENTS"],
        pd.Timestamp("2026-07-20"),
    )

    assert captured["start_date"] == "2026-06-29"
    assert captured["end_date"] == "2026-07-19"

    assert facts.index.tolist() == ["AAA", "NO_EVENTS"]
    assert facts.loc["AAA", "days_since_last_earnings"] == 1
    assert facts.loc["AAA", "days_since_last_activist_13d"] == 4
    assert facts.loc["AAA", "recent_event_codes"] == ["22", "35", "42"]
    assert facts.loc["NO_EVENTS", "recent_event_codes"] == []


def test_purchase_classification_is_an_explicit_attachment():
    transactions = pd.DataFrame(
        [
            _purchase("Routine Owner", "2023-04-10", "2023-04-12"),
            _purchase("Routine Owner", "2024-04-10", "2024-04-12"),
            _purchase("Routine Owner", "2025-04-10", "2025-04-12"),
            _purchase("Routine Owner", "2026-04-10", "2026-04-12"),
            _purchase("Seller", "2026-04-11", "2026-04-13", code="S"),
            _purchase(None, None, "2026-04-14"),
        ]
    )

    result = InsiderSignals.attach_purchase_classification(transactions)

    assert result.iloc[:3]["purchase_classification"].tolist() == ["opportunistic"] * 3
    assert result.iloc[3]["purchase_classification"] == "routine"
    assert pd.isna(result.iloc[4]["purchase_classification"])
    assert result.iloc[5]["purchase_classification"] == "unclassified"


def test_a_pattern_disclosed_late_does_not_make_a_purchase_routine():
    """The label must be decidable from what was knowable when the purchase was
    filed, so a prior April buy disclosed afterwards cannot establish the pattern."""
    transactions = pd.DataFrame(
        [
            _purchase("Owner", "2023-04-10", "2026-05-01"),
            _purchase("Owner", "2024-04-10", "2024-04-12"),
            _purchase("Owner", "2025-04-10", "2025-04-12"),
            _purchase("Owner", "2026-04-10", "2026-04-12"),
        ]
    )

    result = InsiderSignals.attach_purchase_classification(transactions)

    assert result.iloc[3]["purchase_classification"] == "opportunistic"


def test_a_ticker_with_no_filings_counts_zero_but_ratios_stay_null(monkeypatch):
    """No disclosed transaction is a fact, so counts are zero — but a ratio over
    no transactions is undefined, and zero there would read as balanced trading."""
    monkeypatch.setattr(
        "research.signals.sig_insider.daily_repo.get_latest_rows",
        lambda tickers, signal_day: pd.DataFrame(),
    )

    facts = InsiderSignals.attach_activity_facts(
        pd.DataFrame(), ["QUIET"], pd.Timestamp("2026-05-01")
    )
    facts = InsiderSignals.attach_marketcap_normalization(
        facts, pd.Timestamp("2026-05-01")
    )

    assert facts.loc["QUIET", "buy_count_30d"] == 0
    assert facts.loc["QUIET", "buy_value_30d"] == 0.0
    assert np.isnan(facts.loc["QUIET", "net_buy_ratio_90d"])
    assert np.isnan(facts.loc["QUIET", "days_since_last_buy"])
    assert np.isnan(facts.loc["QUIET", "opportunistic_value_to_marketcap"])


def test_insider_activity_facts_include_missing_tickers_and_normalize_marketcap(
    monkeypatch,
):
    transactions = pd.DataFrame(
        [
            _purchase("Routine Owner", "2023-04-10", "2023-04-12"),
            _purchase("Routine Owner", "2024-04-10", "2024-04-12"),
            _purchase("Routine Owner", "2025-04-10", "2025-04-12"),
            _purchase("Routine Owner", "2026-04-10", "2026-04-12"),
            _purchase(
                "Officer A",
                "2026-04-20",
                "2026-04-22",
                value=250_000,
                officer="Y",
            ),
            _purchase(
                "Director B",
                "2026-04-21",
                "2026-04-23",
                value=150_000,
                shares=20,
                director="Y",
            ),
            _purchase(
                "Seller",
                "2026-04-24",
                "2026-04-25",
                code="S",
                value=50_000,
            ),
        ]
    )

    monkeypatch.setattr(
        "research.signals.sig_insider.daily_repo.get_latest_rows",
        lambda tickers, signal_day: pd.DataFrame(
            {"ticker": ["TEST", "EMPTY"], "marketcap": [1_000.0, 1_000.0]}
        ),
    )

    monkeypatch.setattr(
        "research.signals.sig_insider.insider_repo.get",
        lambda **kwargs: transactions,
    )

    frame = InsiderSignals.get_signals(["TEST", "EMPTY"], pd.Timestamp("2026-05-01"))
    labelled = InsiderSignals.attach_purchase_classification(frame)
    facts = InsiderSignals.attach_activity_facts(
        labelled,
        ["TEST", "EMPTY"],
        pd.Timestamp("2026-05-01"),
    )
    facts = InsiderSignals.attach_marketcap_normalization(
        facts,
        pd.Timestamp("2026-05-01"),
    )

    assert facts.loc["TEST", "buy_count_30d"] == 3
    assert facts.loc["TEST", "routine_buy_count_30d"] == 1
    assert facts.loc["TEST", "opportunistic_buy_count_30d"] == 2
    assert facts.loc["TEST", "opportunistic_buy_value_30d"] == 400_000
    assert facts.loc[
        "TEST", "max_purchase_fraction_of_post_holdings_30d"
    ] == pytest.approx(0.2)
    # 1,000 USD millions is a $1bn cap, so $400k of opportunistic buying is 4bp.
    assert facts.loc["TEST", "opportunistic_value_to_marketcap"] == pytest.approx(
        0.0004
    )
    assert facts.loc["EMPTY", "buy_count_30d"] == 0
    assert facts.loc["EMPTY", "opportunistic_value_to_marketcap"] == 0.0


def test_institutional_ownership_enforces_availability_and_computes_qoq(
    monkeypatch,
):
    captured = {}
    quarters = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "date": ["2025-12-31", "2026-03-31"],
            "shrholders": [200, 240],
            "shrunits": [10_000.0, 15_000.0],
            "shrvalue": [100.0, 150.0],
            "percentoftotal": [0.01, 0.02],
            "putvalue": [4.0, 6.0],
            "cllvalue": [2.0, 3.0],
        }
    )

    def fake_get(**kwargs):
        captured.update(kwargs)
        return quarters

    monkeypatch.setattr(
        "research.signals.sig_institutional.institutional_repo.get",
        fake_get,
    )

    frame = InstitutionalSignals.get_signals(
        ["AAA", "EMPTY"], pd.Timestamp("2026-06-30")
    )
    facts = InstitutionalSignals.attach_ownership_facts(
        frame,
        ["AAA", "EMPTY"],
        pd.Timestamp("2026-06-30"),
    )

    assert captured["end_date"] == "2026-05-16"
    assert facts.loc["AAA", "inst_quarter_end"] == pd.Timestamp("2026-03-31")
    assert facts.loc["AAA", "inst_holders"] == 240
    assert facts.loc["AAA", "inst_holders_change"] == 40
    assert facts.loc["AAA", "inst_units_change_pct"] == pytest.approx(0.5)
    assert facts.loc["AAA", "inst_value_change_pct"] == pytest.approx(0.5)
    assert facts.loc["AAA", "inst_put_call_ratio"] == pytest.approx(2.0)


def test_institutional_absence_stays_null_rather_than_zero(monkeypatch):
    """No 13F reporting a ticker is missing data, not ownership of zero."""
    facts = InstitutionalSignals.attach_ownership_facts(
        pd.DataFrame(), ["EMPTY"], pd.Timestamp("2026-06-30")
    )

    assert np.isnan(facts.loc["EMPTY", "inst_holders"])
    assert np.isnan(facts.loc["EMPTY", "inst_units_change_pct"])


def test_a_single_available_quarter_leaves_changes_null(monkeypatch):
    """One quarter cannot show a change; zero would read as no change."""
    quarter = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "date": [pd.Timestamp("2026-03-31")],
            "shrholders": [240],
            "shrunits": [15_000.0],
            "shrvalue": [150.0],
            "percentoftotal": [0.02],
            "putvalue": [None],
            "cllvalue": [None],
        }
    )

    facts = InstitutionalSignals.attach_ownership_facts(
        quarter, ["AAA"], pd.Timestamp("2026-06-30")
    )

    assert facts.loc["AAA", "inst_holders"] == 240
    assert np.isnan(facts.loc["AAA", "inst_holders_change"])
    assert np.isnan(facts.loc["AAA", "inst_put_call_ratio"])
