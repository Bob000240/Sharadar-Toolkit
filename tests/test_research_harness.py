import pandas as pd
import pytest

import research.harness as harness
from research.harness import _forward_returns, _managed_returns


def test_forward_returns_use_adjusted_closes():
    """Dividends/corporate actions belong in both pick and benchmark returns."""

    def prices(**_kwargs):
        return pd.DataFrame(
            {
                "ticker": ["DIV", "DIV"],
                "date": ["2024-01-02", "2024-02-01"],
                "close": [100.0, 100.0],
                "closeadj": [90.0, 100.0],
            }
        )

    returns = _forward_returns(
        ["DIV"],
        signal_day="2024-01-01",
        exit_by="2024-02-01",
        get_fn=prices,
    )

    assert returns["DIV"] == pytest.approx(100.0 / 90.0 - 1)


def test_forward_returns_drop_invalid_adjusted_closes():
    def prices(**_kwargs):
        return pd.DataFrame(
            {
                "ticker": ["BAD", "BAD", "GOOD", "GOOD"],
                "date": [
                    "2024-01-02",
                    "2024-02-01",
                    "2024-01-02",
                    "2024-02-01",
                ],
                "close": [10.0, 11.0, 10.0, 11.0],
                "closeadj": [0.0, 11.0, 10.0, 11.0],
            }
        )

    returns = _forward_returns(
        ["BAD", "GOOD"],
        signal_day="2024-01-01",
        exit_by="2024-02-01",
        get_fn=prices,
    )

    assert "BAD" not in returns
    assert returns["GOOD"] == pytest.approx(0.1)


def test_managed_horizon_return_uses_adjusted_closes(monkeypatch):
    prices = pd.DataFrame(
        {
            "ticker": ["DIV", "DIV", "DIV"],
            "date": ["2024-01-02", "2024-01-03", "2024-02-01"],
            "open": [100.0, 100.0, 100.0],
            "close": [100.0, 100.0, 100.0],
            "closeadj": [90.0, 95.0, 100.0],
        }
    )
    monkeypatch.setattr(harness.equity_repo, "get", lambda **_kwargs: prices)
    monkeypatch.setattr(
        harness.technical_features_repo,
        "get",
        lambda **_kwargs: pd.DataFrame(),
    )

    class NeverExit:
        @staticmethod
        def evaluate(*_args):
            return None

    returns = _managed_returns(
        ["DIV"],
        signal_day="2024-01-01",
        exit_by="2024-02-01",
        monitor=NeverExit(),
    )

    assert returns.loc["DIV", "ret"] == pytest.approx(100.0 / 90.0 - 1)
