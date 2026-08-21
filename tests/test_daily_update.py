from datetime import date

import pandas as pd

import database.source.daily_repo as daily_repo
import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
import database.source.institutional_repo as institutional_repo
import database.source.technical_features_repo as technical_features_repo
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
        daily_update.tickers_repo, "get_sync_cursor", lambda: "2026-07-20"
    )
    monkeypatch.setattr(
        daily_update.tickers_repo, "insert", lambda df: inserted.append(df)
    )

    daily_update.update_tickers(FakeSharadar())

    assert calls[0] == {"table": "SEP", "lastupdated_since": "2026-07-20"}
    assert calls[1] == {"table": "SFP", "lastupdated_since": "2026-07-20"}
    assert len(inserted[0]) == 2


def test_institutional_update_re_exports_the_newest_stored_quarter(monkeypatch):
    """A quarter is partial until its 13F filings arrive, so the newest stored
    one is re-exported rather than skipped."""
    calls = []
    monkeypatch.setattr(
        daily_update.institutional_repo, "get_sync_cursor", lambda: "2026-06-30"
    )
    monkeypatch.setattr(
        daily_update,
        "load_sharadar_table",
        lambda code, start_date, upsert: calls.append((code, start_date, upsert)),
    )

    daily_update.update_institutional()

    assert calls == [("SF3A", "2026-06-30", True)]


def test_institutional_update_backfills_when_nothing_is_stored(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_update.institutional_repo, "get_sync_cursor", lambda: None
    )
    monkeypatch.setattr(
        daily_update,
        "load_sharadar_table",
        lambda code, start_date, upsert: calls.append((code, start_date, upsert)),
    )

    daily_update.update_institutional()

    assert calls == [("SF3A", daily_update.START_DATE, True)]


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

    monkeypatch.setattr(daily_update.technical_features_repo, "is_empty", lambda: False)
    monkeypatch.setattr(
        daily_update.technical_features_repo,
        "get_stale_feature_tickers",
        lambda: [],
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


def test_stale_tickers_rebuild_whole_history_not_just_missing_dates(monkeypatch):
    """Re-adjusted prices leave feature rows present-but-wrong, which the
    missing-date scan cannot see. Every rolling window depends on the full
    series, so the repair has to span the ticker's entire history."""
    rebuilt = []
    prices = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "date": date(2026, 6, 30),
                "close": 5.0,
                "high": 5.5,
                "low": 4.5,
                "volume": 100,
            },
            {
                "ticker": "TEST",
                "date": date(2026, 7, 1),
                "close": 5.5,
                "high": 6.0,
                "low": 5.0,
                "volume": 110,
            },
        ]
    )

    monkeypatch.setattr(daily_update.technical_features_repo, "is_empty", lambda: False)
    monkeypatch.setattr(
        daily_update.technical_features_repo,
        "get_stale_feature_tickers",
        lambda: ["TEST"],
    )
    monkeypatch.setattr(
        daily_update.technical_features_repo,
        "get_missing_feature_dates",
        lambda: pd.DataFrame([{"ticker": "TEST", "date": date(2026, 7, 1)}]),
    )
    monkeypatch.setattr(daily_update.equity_repo, "get", lambda **kwargs: prices.copy())
    monkeypatch.setattr(
        daily_update.technical_features_repo, "insert", lambda df: rebuilt.append(df)
    )

    daily_update.update_technical_features()

    assert len(rebuilt) == 1
    assert rebuilt[0]["date"].tolist() == [date(2026, 6, 30), date(2026, 7, 1)]


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
                {column: None for column in institutional_repo._COLUMNS}
                | {"ticker": "TEST", "date": "2026-03-31", "shrholders": 4}
            ]
        )
    )

    ticker_sql = ticker_engine.statements[0][0]
    institutional_sql = institutional_engine.statements[0][0]
    assert "ON CONFLICT (ticker, table_code, permaticker) DO UPDATE" in ticker_sql
    assert "ON CONFLICT (ticker, date)" in institutional_sql
    assert "isdelisted = COALESCE(EXCLUDED.isdelisted" in ticker_sql
    assert "shrholders = EXCLUDED.shrholders" in institutional_sql


def test_equity_price_sync_uses_lastupdated_not_date(monkeypatch):
    """A split makes Sharadar re-adjust a ticker's whole history in place. Those
    rewrites keep their ORIGINAL dates, so only a lastupdated cursor sees them."""
    calls = []

    class FakeSharadar:
        def equity_prices(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame([{"ticker": "TEST", "date": date(2019, 3, 1)}])

    monkeypatch.setattr(
        daily_update.equity_repo, "get_sync_cursor", lambda: "2026-07-22"
    )
    monkeypatch.setattr(daily_update.equity_repo, "insert", lambda df: None)

    daily_update.update_equity_prices(FakeSharadar())

    assert calls == [{"lastupdated_since": "2026-07-22"}]


def test_fundamentals_sync_catches_restatements_of_old_periods(monkeypatch):
    """A 10-K/A amending FY2019 carries calendardate=2019-12-31, so a recent
    calendardate window structurally cannot contain it."""
    calls = []

    class FakeSharadar:
        def fundamentals(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame()

    monkeypatch.setattr(
        daily_update.fundamentals_repo, "get_sync_cursor", lambda: "2026-07-23"
    )

    daily_update.update_fundamentals(FakeSharadar())

    assert calls == [{"lastupdated_since": "2026-07-23"}]


def test_price_and_feature_conflicts_update_existing_rows(monkeypatch):
    """DO NOTHING would fetch Sharadar's re-adjusted rows and then throw them
    away, since the (ticker, date) key already exists."""
    engines = {}
    for module, name in (
        (equity_repo, "equity"),
        (fund_repo, "fund"),
        (daily_repo, "daily"),
        (technical_features_repo, "features"),
    ):
        engines[name] = _RecordingEngine()
        monkeypatch.setattr(module, "get_connection", lambda e=engines[name]: e)

    price_row = {column: None for column in equity_repo._COLUMNS}
    price_row.update({"ticker": "TEST", "date": "2026-07-22", "close": 1.0})
    equity_repo.insert(pd.DataFrame([price_row]))
    fund_repo.insert(pd.DataFrame([price_row]))

    daily_row = {column: None for column in daily_repo._COLUMNS}
    daily_row.update({"ticker": "TEST", "date": "2026-07-22", "marketcap": 1.0})
    daily_repo.insert(pd.DataFrame([daily_row]))

    feature_row = {column: None for column in technical_features_repo._COLUMNS}
    feature_row.update({"ticker": "TEST", "date": "2026-07-22", "close": 1.0})
    technical_features_repo.insert(pd.DataFrame([feature_row]))

    for name, table, revised in (
        ("equity", "equity_prices", "close"),
        ("fund", "fund_prices", "close"),
        ("daily", "daily_valuation", "marketcap"),
        ("features", "technical_features", "close"),
    ):
        sql = engines[name].statements[0][0]
        assert f"INSERT INTO {table}" in sql
        assert "ON CONFLICT (ticker, date) DO UPDATE" in sql, table
        assert f"{revised} = EXCLUDED.{revised}" in sql, table
