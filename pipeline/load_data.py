"""Full initial data load, run once after the tables exist.

::

    uv run python -m pipeline.load_data

Raw Sharadar tables are bulk-exported as zipped CSV and COPY'd into Postgres,
which includes delisted tickers so the history carries no survivorship bias.
Technical features are then computed locally.

The technical features are local on purpose: no vendor table carries historical
indicators. SHARADAR/METRICS looked like one but serves a one-row-per-ticker
snapshot, so derived history can only be built here.
"""

import glob
import os
import sys
import tempfile
import zipfile

import numpy as np
import pandas as pd
import nasdaqdatalink
from dotenv import load_dotenv

from data.technical_features import compute_technical_features
from pipeline import datasets, report

import database.source.daily_repo as daily_repo
import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
import database.source.technical_features_repo as technical_features_repo
import database.source.tickers_repo as tickers_repo
import database.source.fundamentals_repo as fundamentals_repo
import database.source.insider_repo as insider_repo
import database.source.institutional_repo as institutional_repo
import database.source.event_repo as event_repo
from database.bulk_copy import copy_insert

load_dotenv()
nasdaqdatalink.ApiConfig.api_key = os.getenv("NDL_APIKEY")

START_DATE = "2016-01-01"
END_DATE = pd.Timestamp.today().strftime("%Y-%m-%d")

SHARADAR_TABLES = {
    "TICKERS": (tickers_repo, "tickers", None),
    "SEP": (equity_repo, "equity_prices", "date"),
    "SFP": (fund_repo, "fund_prices", "date"),
    "SF1": (fundamentals_repo, "fundamentals", "calendardate"),
    "SF2": (insider_repo, "insider_transactions", "filingdate"),
    "SF3A": (institutional_repo, "institutional_ownership", "date"),
    "EVENTS": (event_repo, "events", "date"),
    "DAILY": (daily_repo, "daily_valuation", "date"),
}
_RENAMES = {"TICKERS": {"table": "table_code"}}
_TICKER_TABLE_CODES = ("SEP", "SFP")
_ROW_FILTERS = {
    "TICKERS": lambda df: df[df["table_code"].isin(_TICKER_TABLE_CODES)],
}


def _rescale_holdings(chunk: pd.DataFrame) -> pd.DataFrame:
    """Restore SF3 v3 holdings to whole shares and whole dollars.

    v3 reports every ``*units`` column in thousands and every ``*value`` column
    in millions, checked against the previous version's rows and against the
    close that value over units implies. Stored raw they would be off by orders
    of magnitude, invisibly. ``percentoftotal`` is already a percentage.
    """
    chunk = chunk.copy()
    for column in chunk.columns:
        if column.endswith("units"):
            chunk[column] = chunk[column] * 1e3
        elif column.endswith("value"):
            chunk[column] = chunk[column] * 1e6
    return chunk


_TRANSFORMS = {"SF3A": _rescale_holdings}
_LABELS = {
    datasets.code(name): datasets.label(name)
    for name in datasets.DATASETS
    if datasets.code(name)
}
_CHUNK = 200_000


def _export(code: str, dest: str, date_field: str | None, start_date: str) -> list[str]:
    """Export one Sharadar table to zipped CSV and unpack it.

    Return the paths of the extracted CSV parts. Raise RuntimeError when the export
    produced nothing, which otherwise surfaces much later as an empty table.
    """
    filters: dict = {}
    if date_field:
        filters[date_field] = {"gte": start_date}
    zip_path = os.path.join(dest, f"{code}.zip")
    nasdaqdatalink.export_table(f"SHARADAR/{code}", filename=zip_path, **filters)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)
    files = sorted(glob.glob(os.path.join(dest, "*.csv")))
    if not files:
        raise RuntimeError(f"no CSV produced for {code} (in {dest})")
    return files


def load_sharadar_table(
    code: str, start_date: str = START_DATE, upsert: bool = False
) -> int:
    """Bulk-load one Sharadar table into its Postgres table.

    Streamed in chunks so a multi-gigabyte export never has to fit in memory. Rows
    with no ticker are dropped, since they cannot be joined to anything.
    ``upsert``
    overwrites what a refresh re-exports rather than skipping it, and deduplicates
    each chunk, because Postgres refuses a DO UPDATE touching one row twice.
    """
    repo, table, date_field = SHARADAR_TABLES[code]
    rename = _RENAMES.get(code)
    row_filter = _ROW_FILTERS.get(code)
    transform = _TRANSFORMS.get(code)
    conflict = repo.CONFLICT if upsert else "ON CONFLICT DO NOTHING"
    total = 0
    with tempfile.TemporaryDirectory() as dest:
        for part in _export(code, dest, date_field, start_date):
            for chunk in pd.read_csv(part, chunksize=_CHUNK):
                if rename:
                    chunk = chunk.rename(columns=rename)
                if "ticker" in chunk.columns:
                    chunk = chunk[chunk["ticker"].notna()]
                if row_filter is not None:
                    chunk = row_filter(chunk)
                if transform is not None:
                    chunk = transform(chunk)
                if upsert:
                    chunk = chunk.drop_duplicates(list(repo.KEY_COLUMNS), keep="last")
                if not chunk.empty:
                    total += copy_insert(table, repo._COLUMNS, chunk, conflict)
    return total


def load_sharadar_bulk(run: report.Run) -> None:
    """Load every configured Sharadar table in order, reporting each."""
    for code in SHARADAR_TABLES:
        with run.step(_LABELS[code], f"exporting SHARADAR/{code}") as result:
            result.rows = load_sharadar_table(code)


def load_technical_features() -> int:
    """Compute technical features for every ticker and store them.

    Batched by ticker, and each ticker's full price history is passed in one piece
    because every rolling window depends on the whole series. Infinities become
    NULL, since a ratio against a zero denominator is not a number the database
    should carry.
    """
    symbols = equity_repo.get_latest_dates()["ticker"].tolist()
    total = 0
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        df = equity_repo.get(tickers=batch, start_date=START_DATE)
        if df.empty:
            continue
        parts = [
            compute_technical_features(g.reset_index(drop=True))
            for _, g in df.sort_values(["ticker", "date"]).groupby("ticker", sort=False)
        ]
        feature_frame = pd.concat(parts, ignore_index=True).replace(
            [np.inf, -np.inf],
            np.nan,
        )
        total += copy_insert(
            "technical_features",
            technical_features_repo._COLUMNS,
            feature_frame,
        )
        print(
            f"  batch {i // 50 + 1}/{-(-len(symbols) // 50)}: "
            f"{len(feature_frame):,} rows"
        )
    return total


def main() -> list[str]:
    """Run the full load: raw tables first, then derived features.

    Return the labels that failed, so a caller can set an exit status. A failed
    dataset no longer abandons the rest, since they are independent.
    """
    run = report.Run("load", "all datasets", f"{START_DATE} → {END_DATE}")
    load_sharadar_bulk(run)
    with run.step(datasets.label("technicals"), "computing from equity prices") as step:
        step.rows = load_technical_features()
    return run.finish()


if __name__ == "__main__":
    if not os.getenv("NDL_APIKEY"):
        sys.exit("Set NDL_APIKEY (your Nasdaq Data Link key) in .env")
    sys.exit(1 if main() else 0)
