import numpy as np
import pandas as pd
import pytest

from data.signals.sig import Signals
from data.signals.sig_events import EventSignals
from data.signals.sig_insider import InsiderSignals
from data.signals.sig_institutional import InstitutionalSignals


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

    monkeypatch.setattr("data.signals.sig_events.event_repo.get", fake_get)
    facts = EventSignals.attach_event_facts(
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

    assert result.iloc[:3]["purchase_classification"].tolist() == [
        "opportunistic"
    ] * 3
    assert result.iloc[3]["purchase_classification"] == "routine"
    assert pd.isna(result.iloc[4]["purchase_classification"])
    assert result.iloc[5]["purchase_classification"] == "unclassified"


def test_insider_activity_facts_include_missing_tickers_and_normalize_marketcap():
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

    facts = InsiderSignals.attach_activity_facts(
        transactions,
        ["TEST", "EMPTY"],
        pd.Timestamp("2026-05-01"),
    )
    facts = InsiderSignals.attach_marketcap_normalization(
        facts,
        pd.Series({"TEST": 1_000_000_000, "EMPTY": 1_000_000_000}),
    )

    assert facts.loc["TEST", "buy_count_30d"] == 3
    assert facts.loc["TEST", "routine_buy_count_30d"] == 1
    assert facts.loc["TEST", "opportunistic_buy_count_30d"] == 2
    assert facts.loc["TEST", "opportunistic_buy_value_30d"] == 400_000
    assert facts.loc[
        "TEST", "max_purchase_fraction_of_post_holdings_30d"
    ] == pytest.approx(0.2)
    assert facts.loc["TEST", "opportunistic_value_to_marketcap"] == pytest.approx(
        0.0004
    )
    assert facts.loc["EMPTY", "buy_count_30d"] == 0
    assert facts.loc["EMPTY", "opportunistic_value_to_marketcap"] == 0.0


def test_institutional_get_enforces_availability_and_attachment_computes_qoq(
    monkeypatch,
):
    captured = {}
    holdings = pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "AAA", "AAA"],
            "investorname": ["Old", "Closed", "Old", "New"],
            "calendardate": [
                "2025-12-31",
                "2025-12-31",
                "2026-03-31",
                "2026-03-31",
            ],
            "value": [100.0, 100.0, 150.0, 150.0],
            "units": [10.0, 10.0, 15.0, 15.0],
            "securitytype": ["SHR", "SHR", "SHR", "SHR"],
        }
    )

    def fake_get(**kwargs):
        captured.update(kwargs)
        return holdings

    monkeypatch.setattr(
        "data.signals.sig_institutional.institutional_repo.get",
        fake_get,
    )
    raw = InstitutionalSignals.get_signals(
        ["AAA", "EMPTY"],
        pd.Timestamp("2026-06-30"),
    )

    assert captured["end_date"] == "2026-05-16"
    assert "total_holders" not in raw

    facts = InstitutionalSignals.attach_holding_facts(
        raw,
        ["AAA", "EMPTY"],
        pd.Timestamp("2026-06-30"),
    )

    assert facts.loc["AAA", "quarter_end"] == pd.Timestamp("2026-03-31")
    assert facts.loc["AAA", "total_holders"] == 2
    assert facts.loc["AAA", "value_change_pct"] == pytest.approx(0.5)
    assert facts.loc["AAA", "new_holders"] == 1
    assert facts.loc["AAA", "closed_positions"] == 1
    assert np.isnan(facts.loc["EMPTY", "value_change_pct"])
