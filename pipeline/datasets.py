"""The dataset vocabulary shared by the CLI, the loader, and the daily update.

One name per Sharadar table, carrying the vendor code, the repository behind it,
and the label every command prints. It lives here so the three paths cannot
drift into calling the same thing ``SF3A``, ``Institutional ownership``, and
``institutional`` in one session.
"""

import importlib

# name -> (Sharadar code, repository module, printed label)
DATASETS = {
    "tickers": ("TICKERS", "tickers_repo", "Tickers"),
    "equity": ("SEP", "equity_repo", "Equity prices"),
    "fund": ("SFP", "fund_repo", "Fund prices"),
    "fundamentals": ("SF1", "fundamentals_repo", "Fundamentals"),
    "insider": ("SF2", "insider_repo", "Insider"),
    "institutional": ("SF3A", "institutional_repo", "Institutional"),
    "events": ("EVENTS", "event_repo", "Events"),
    "daily": ("DAILY", "daily_repo", "Daily valuation"),
    "technicals": (None, "technical_features_repo", "Technical features"),
}
_BY_CODE = {code: name for name, (code, _, _) in DATASETS.items() if code}


def code(dataset: str) -> str | None:
    """Return the Sharadar table code, or None where the data is derived."""
    return DATASETS[dataset][0]


def label(dataset: str) -> str:
    """Return the label commands print for this dataset."""
    return DATASETS[dataset][2]


def repo(dataset: str):
    """Import and return the repository module backing this dataset."""
    return importlib.import_module(f"database.source.{DATASETS[dataset][1]}")


def resolve(dataset: str) -> str | None:
    """Return the canonical name for a name or a Sharadar code, else None."""
    if dataset.lower() in DATASETS:
        return dataset.lower()
    return _BY_CODE.get(dataset.upper())
