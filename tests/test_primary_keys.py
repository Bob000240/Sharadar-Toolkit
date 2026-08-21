"""The stored keys against SHARADAR_KEYS.csv, the vendor's own declaration."""

import csv
import importlib
import pathlib

import pytest

_KEYS_FILE = pathlib.Path("SHARADAR_KEYS.csv")

# The repository module behind each vendor table.
_REPOS = {
    "TICKERS": "tickers_repo",
    "SEP": "equity_repo",
    "SFP": "fund_repo",
    "SF1": "fundamentals_repo",
    "SF2": "insider_repo",
    "SF3A": "institutional_repo",
    "EVENTS": "event_repo",
    "DAILY": "daily_repo",
}

# Two columns are stored under a different name than the vendor publishes:
# ``table`` collides with the SQL keyword, and SF3 v3 renamed ``calendardate``
# to ``date`` after this CSV was written.
_RENAMED = {"table": "table_code", "calendardate": "date"}


def _vendor_keys() -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {}
    for row in csv.DictReader(_KEYS_FILE.open()):
        if row["isprimarykey"] == "Y":
            column = _RENAMED.get(row["indicator"], row["indicator"])
            keys.setdefault(row["table"], set()).add(column)
    return keys


@pytest.mark.parametrize("code", sorted(_REPOS))
def test_stored_key_matches_the_vendor_declaration(code):
    """A key narrower than the vendor's silently discards rows on load; one
    containing a nullable column never fires ON CONFLICT at all, so repeat runs
    accumulate duplicates instead."""
    repo = importlib.import_module(f"database.source.{_REPOS[code]}")
    assert set(repo.KEY_COLUMNS) == _vendor_keys()[code]


@pytest.mark.parametrize("code", sorted(_REPOS))
def test_key_columns_are_stored_columns(code):
    repo = importlib.import_module(f"database.source.{_REPOS[code]}")
    assert set(repo.KEY_COLUMNS) <= set(repo._COLUMNS)
