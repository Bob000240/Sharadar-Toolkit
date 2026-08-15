"""Full initial data load. Run once after the tables exist.

::

    uv run python -m pipeline.load_data

Two stages. Raw Sharadar tables are bulk-exported as zipped CSV through the
datatables export endpoint and COPY'd into Postgres, which is both faster than
row-by-row inserts and reproducible, and which includes delisted tickers so the
history carries no survivorship bias. Technical features are then computed
locally from the loaded equity prices.

The incremental delta that keeps this current lives in ``pipeline.daily_update``.
Requires NDL_APIKEY in the environment.
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

from pipeline.config import BENCHMARK_SYMBOLS
from data.technical_features import compute_technical_features

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
    "TICKERS": (tickers_repo, "tickers", None, None),
    "SEP": (equity_repo, "equity_prices", "date", None),
    "SFP": (fund_repo, "fund_prices", "date", BENCHMARK_SYMBOLS),
    "SF1": (fundamentals_repo, "fundamentals", "calendardate", None),
    "SF2": (insider_repo, "insider_transactions", "filingdate", None),
    "SF3": (institutional_repo, "institutional_holdings", "calendardate", None),
    "EVENTS": (event_repo, "events", "date", None),
}
_RENAMES = {"TICKERS": {"table": "table_code"}}
_ROW_FILTERS = {
    "TICKERS": lambda df: df[(df["table_code"] == "SEP") & df["ticker"].notna()],
}
_CHUNK = 200_000


def _export(
    code: str, dest: str, date_field: str | None, tickers: list | None
) -> list[str]:
    """Export one Sharadar table to zipped CSV and unpack it.

    Return the paths of the extracted CSV parts. Raise RuntimeError when the export
    produced nothing, which otherwise surfaces much later as an empty table.
    """
    filters: dict = {}
    if date_field:
        filters[date_field] = {"gte": START_DATE}
    if tickers:
        filters["ticker"] = list(tickers)
    zip_path = os.path.join(dest, f"{code}.zip")
    print(f"  exporting SHARADAR/{code} ...")
    nasdaqdatalink.export_table(f"SHARADAR/{code}", filename=zip_path, **filters)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)
    files = sorted(glob.glob(os.path.join(dest, "*.csv")))
    if not files:
        raise RuntimeError(f"no CSV produced for {code} (in {dest})")
    return files


def load_sharadar_table(code: str) -> None:
    """Bulk-load one Sharadar table into its Postgres table.

    Streamed in chunks so a multi-gigabyte export never has to fit in memory. Rows
    with no ticker are dropped, since they cannot be joined to anything.
    """
    repo, table, date_field, tickers = SHARADAR_TABLES[code]
    rename = _RENAMES.get(code)
    row_filter = _ROW_FILTERS.get(code)
    print(f"Bulk loading {code} -> {table} ...")
    total = 0
    with tempfile.TemporaryDirectory() as dest:
        for part in _export(code, dest, date_field, tickers):
            for chunk in pd.read_csv(part, chunksize=_CHUNK):
                if rename:
                    chunk = chunk.rename(columns=rename)
                chunk = chunk[chunk["ticker"].notna()]
                if row_filter is not None:
                    chunk = row_filter(chunk)
                if not chunk.empty:
                    total += copy_insert(table, repo._COLUMNS, chunk)
    print(f"  {code} total: {total:,} rows")


def load_sharadar_bulk() -> None:
    """Load every configured Sharadar table in order."""
    for code in SHARADAR_TABLES:
        load_sharadar_table(code)


def load_technical_features() -> None:
    """Compute technical features for every ticker and store them.

    Batched by ticker, and each ticker's full price history is passed in one piece
    because every rolling window depends on the whole series. Infinities become
    NULL, since a ratio against a zero denominator is not a number the database
    should carry.
    """
    print("Computing technical features from equity prices (all tickers)...")
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
    print(f"  total: {total:,} rows  ({len(symbols):,} tickers)")


def main() -> None:
    """Run the full load: raw tables first, then derived features."""
    print("=== Sharadar Toolkit full load ===")
    print(f"Date range: {START_DATE} → {END_DATE}\n")
    load_sharadar_bulk()
    load_technical_features()
    print("\n=== Load complete ===")


if __name__ == "__main__":
    if not os.getenv("NDL_APIKEY"):
        sys.exit("Set NDL_APIKEY (your Nasdaq Data Link key) in .env")
    main()
