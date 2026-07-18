"""
Full data load. Run once after setup_db.py.

    uv run python -m set_up.load_data        # NDL_APIKEY + FRED_API_KEY from .env

Three stages:
  1. Raw Sharadar tables  -> bulk-exported as zipped CSV (Nasdaq datatables export,
     which runs on the table-API entitlement) and COPY'd into Postgres
     (fast + reproducible; includes delisted tickers).
  2. `indicators`         -> computed locally from equity_prices.
  3. `macro`              -> pulled from FRED.

The incremental delta (API-based) lives in set_up/daily_update.py.
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

from set_up.config import get_stock_symbols, BENCHMARK_SYMBOLS
from data.macro_data import MacroData
from data.indicators import compute_indicators

import database.market.equity_repo as equity_repo
import database.market.fund_repo as fund_repo
import database.market.indicators_repo as indicators_repo
import database.market.tickers_repo as tickers_repo
import database.market.fundamentals_repo as fundamentals_repo
import database.market.insider_repo as insider_repo
import database.market.institutional_repo as institutional_repo
import database.market.event_repo as event_repo
import database.market.macro_repo as macro_repo
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


# ── Stage 1: raw Sharadar tables (bulk CSV export -> COPY) ───────────────


def _export(code: str, dest: str, date_field: str | None, tickers: list | None) -> list[str]:
    # Datatables bulk export (qopts.export) runs on the table-API entitlement,    filters: dict = {}
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
    for code in SHARADAR_TABLES:
        load_sharadar_table(code)


# ── Stage 2: indicators computed from equity_prices ──────────────────────


def load_indicators() -> None:
    # Compute indicators for EVERY ticker in equity_prices, incl. delisted — not
    # get_stock_symbols() (the current tradeable universe). Curating here is what
    # bakes survivorship bias into every backtest: delisted names would have
    # prices but no technicals, so a historical screen never sees the losers.
    # The universe is narrowed point-in-time at screen time instead.
    print("Computing indicators from equity prices (all tickers)...")
    symbols = equity_repo.get_latest_dates()["ticker"].tolist()
    total = 0
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        df = equity_repo.get(tickers=batch, start_date=START_DATE)
        if df.empty:
            continue
        parts = [
            compute_indicators(g.reset_index(drop=True))
            for _, g in df.sort_values(["ticker", "date"]).groupby("ticker", sort=False)
        ]
        ind_df = pd.concat(parts, ignore_index=True).replace([np.inf, -np.inf], np.nan)
        total += copy_insert("indicators", indicators_repo._COLUMNS, ind_df)
        print(f"  batch {i // 50 + 1}/{-(-len(symbols) // 50)}: {len(ind_df):,} rows")
    print(f"  total: {total:,} rows  ({len(symbols):,} tickers)")


# ── Stage 3: macro from FRED ─────────────────────────────────────────────


def load_macro() -> None:
    print("Loading macro data (FRED)...")
    df = MacroData().get_macro(START_DATE, END_DATE)
    macro_repo.insert(df)  # COALESCE upsert; keep repo.insert (small table)
    print(f"  {len(df):,} rows")


def main() -> None:
    print("=== QuorumNexus full load ===")
    print(f"Date range: {START_DATE} → {END_DATE}\n")
    load_sharadar_bulk()
    print(f"\nScreening universe (current, liquid): {len(get_stock_symbols())} stocks")
    print("(indicators are computed for all tickers, not just this universe)\n")
    load_indicators()
    load_macro()
    print("\n=== Load complete ===")


if __name__ == "__main__":
    if not os.getenv("NDL_APIKEY"):
        sys.exit("Set NDL_APIKEY (your Nasdaq Data Link key) in .env")
    main()
