import pandas as pd
import pytest

from data.signals.sig_technical import TechnicalSignals


def _technical_feature_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "STALE"],
            "date": pd.to_datetime(["2026-07-17"] * 3 + ["2025-01-01"]),
            "close": [30.0, 20.0, 10.0, 100.0],
            "return_5d": [0.30, 0.20, 0.10, 1.0],
            "return_20d": [0.30, 0.20, 0.10, 1.0],
            "return_60d": [0.30, 0.20, 0.10, 1.0],
            "return_252d": [0.30, 0.20, 0.10, 1.0],
            "sql_value": [3, 2, 1, 100],
        }
    )


def _attach_test_sectors(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["sector"] = pd.Series(
        {
            "AAA": "Technology",
            "BBB": "Technology",
            "CCC": "Energy",
            "STALE": "Technology",
        }
    )
    return result


def _benchmark_prices() -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-07-17", periods=21)
    return pd.DataFrame(
        {
            "ticker": ["SPY"] * 21,
            "date": dates,
            "close": range(1, 22),
        }
    )


def test_get_signals_returns_only_requested_sql_rows(monkeypatch):
    monkeypatch.setattr(
        TechnicalSignals,
        "attach_sectors",
        staticmethod(_attach_test_sectors),
    )
    monkeypatch.setattr(
        "data.signals.sig_technical.technical_features_repo.get_latest_rows",
        lambda tickers, signal_day: _technical_feature_rows(),
    )

    result = TechnicalSignals.get_signals(
        ["CCC", "BBB"],
        pd.Timestamp("2026-07-18"),
    )

    assert result.index.tolist() == ["CCC", "BBB"]
    assert result.loc["BBB", "sql_value"] == 2
    assert "sector" not in result
    assert "return_20d_percentile" not in result
    assert "sector_rank_20d" not in result


def test_strategy_can_opt_into_technical_attachments(monkeypatch):
    monkeypatch.setattr(
        TechnicalSignals,
        "attach_sectors",
        staticmethod(_attach_test_sectors),
    )
    monkeypatch.setattr(
        "data.signals.sig_technical.technical_features_repo.get_latest_rows",
        lambda tickers, signal_day: _technical_feature_rows(),
    )
    monkeypatch.setattr(
        "data.signals.sig_technical.fund_repo.get",
        lambda **kwargs: _benchmark_prices(),
    )

    result = TechnicalSignals.get_signals(
        ["CCC", "BBB"],
        pd.Timestamp("2026-07-18"),
    )
    result = TechnicalSignals.attach_sectors(result)
    result = TechnicalSignals.attach_return_percentiles(result)

    assert result.loc["BBB", "return_20d_percentile"] == 100.0
    assert "excess_return_20d" not in result

    result = TechnicalSignals.attach_market_relative_returns(
        result,
        pd.Timestamp("2026-07-18"),
    )
    assert "excess_return_20d" in result


def test_get_signals_omits_unavailable_requested_ticker(monkeypatch):
    monkeypatch.setattr(
        "data.signals.sig_technical.technical_features_repo.get_latest_rows",
        lambda tickers, signal_day: _technical_feature_rows(),
    )

    result = TechnicalSignals.get_signals(
        ["MISSING"],
        pd.Timestamp("2026-07-18"),
    )

    assert result.empty
