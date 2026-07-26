from datetime import date

import pandas as pd

import database.source.institutional_repo as institutional_repo
import database.source.tickers_repo as tickers_repo
import pipeline.daily_update as daily_update


class _ConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class _RecordingEngine:
    def __init__(self):
        self.statements = []

    def begin(self):
        engine = self

        class _Connection:
            def execute(self, statement, records):
                engine.statements.append((str(statement), records))

        return _ConnectionContext(_Connection())


def test_ticker_refresh_includes_delisted_rows(monkeypatch):
    calls = []
    inserted = []

    class FakeSharadar:
        def tickers(self, **kwargs):
            calls.append(kwargs)
            table = kwargs["table"]
            return pd.DataFrame([{"ticker": "TEST", "table": table, "isdelisted": "Y"}])

    monkeypatch.setattr(
        daily_update.tickers_repo, "insert", lambda df: inserted.append(df)
    )

    daily_update.update_tickers(FakeSharadar())

    assert calls[0] == {"table": "SEP"}
    assert calls[1] == {
        "table": "SFP",
        "tickers": daily_update.BENCHMARK_SYMBOLS,
    }
    assert len(inserted[0]) == 2


def test_technical_feature_update_normalizes_database_dates(monkeypatch):
    inserted = []
    prices = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "date": date(2026, 6, 30),
                "close": 10.0,
                "high": 11.0,
                "low": 9.0,
                "volume": 100,
            },
            {
                "ticker": "TEST",
                "date": date(2026, 7, 1),
                "close": 11.0,
                "high": 12.0,
                "low": 10.0,
                "volume": 110,
            },
        ]
    )

    monkeypatch.setattr(
        daily_update.technical_features_repo,
        "get_latest_dates",
        lambda: pd.DataFrame([{"ticker": "TEST", "latest_date": date(2026, 6, 30)}]),
    )
    monkeypatch.setattr(
        daily_update.technical_features_repo,
        "get_missing_feature_dates",
        lambda: pd.DataFrame([{"ticker": "TEST", "date": date(2026, 7, 1)}]),
    )
    monkeypatch.setattr(
        daily_update.equity_repo,
        "get",
        lambda **kwargs: prices.copy(),
    )
    monkeypatch.setattr(
        daily_update.technical_features_repo,
        "insert",
        lambda df: inserted.append(df),
    )

    daily_update.update_technical_features()

    assert len(inserted) == 1
    assert inserted[0]["date"].tolist() == [pd.Timestamp("2026-07-01")]


def test_ticker_and_institutional_conflicts_update_existing_rows(monkeypatch):
    ticker_engine = _RecordingEngine()
    institutional_engine = _RecordingEngine()
    monkeypatch.setattr(tickers_repo, "get_connection", lambda: ticker_engine)
    monkeypatch.setattr(
        institutional_repo,
        "get_connection",
        lambda: institutional_engine,
    )

    ticker_row = {column: None for column in tickers_repo._COLUMNS}
    ticker_row.update({"ticker": "TEST", "table_code": "SEP", "isdelisted": "Y"})
    tickers_repo.insert(pd.DataFrame([ticker_row]))
    institutional_repo.insert(
        pd.DataFrame(
            [
                {
                    "ticker": "TEST",
                    "investorname": "Investor",
                    "calendardate": "2026-03-31",
                    "value": 2.0,
                    "units": 1.0,
                    "price": 2.0,
                    "securitytype": "SHR",
                }
            ]
        )
    )

    ticker_sql = ticker_engine.statements[0][0]
    institutional_sql = institutional_engine.statements[0][0]
    assert "ON CONFLICT (ticker, table_code) DO UPDATE" in ticker_sql
    assert "isdelisted = COALESCE(EXCLUDED.isdelisted" in ticker_sql
    assert "DO UPDATE SET value = EXCLUDED.value" in institutional_sql
