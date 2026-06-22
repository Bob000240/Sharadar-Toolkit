"""
Initial data load script.
Assumes setup_db.py has already been run (all tables exist and are empty).

Run order:
  1. python set_up/setup_db.py      -- drops and recreates all tables
  2. python set_up/load_data.py     -- populates all tables from source APIs
  3. python set_up/daily_update.py  -- daily incremental refresh thereafter

Data sources:
  - OHLCV + indicators:   Alpaca (unchanged)
  - Descriptors:          Sharadar TICKERS
  - Fundamentals:         Sharadar SF1
  - Insider:              Sharadar SF2
  - Institutional:        Sharadar SF3A (summary)
  - Market metrics:       Sharadar DAILY, METRICS, EVENTS, ACTIONS, SP500
  - Fund prices:          Sharadar SFP (sector ETFs)
  - Macro:                FRED (unchanged)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from set_up.config import STOCK_SYMBOLS, ALL_SYMBOLS, BENCHMARK_SYMBOLS
from data_det.raw_data.sharadar_data import SharadarData
from data_det.raw_data.market_data import MarketData
from data_det.processed_data.indicators import compute_indicators
import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
import database.descriptors_repository as descriptor_repo
import database.fundamentals_repository as fund_repo
import database.institutional_repository as inst_repo
import database.market_metrics_repository as mm_repo

START_DATE = "2021-01-01"
END_DATE   = pd.Timestamp.today().strftime("%Y-%m-%d")
SECTOR_ETFS = [s for s in BENCHMARK_SYMBOLS if s != "SPY"]


def load_ohlcv() -> None:
    print("Loading OHLCV from Alpaca...")
    df = MarketData().get_OHLCV(ALL_SYMBOLS, START_DATE, END_DATE)
    if not df.empty:
        market_repo.insert_OHLCV_table(df)
        print(f"  {len(df):,} rows inserted")
    else:
        print("  No data returned")


def load_indicators() -> None:
    print("Computing and loading indicators...")
    count = 0
    for sym in ALL_SYMBOLS:
        df = market_repo.get_OHLCV(sym, START_DATE, END_DATE)
        if df.empty:
            continue
        ind = compute_indicators(df.sort_values("date").reset_index(drop=True))
        if not ind.empty:
            indicator_repo.insert_indicators(ind)
            count += len(ind)
    print(f"  {count:,} indicator rows inserted")


def load_descriptors(sh: SharadarData) -> None:
    print("Loading descriptors from Sharadar TICKERS...")
    df = sh.tickers(table="SEP", is_delisted=False)
    if not df.empty:
        descriptor_repo.insert_descriptors(df)
        print(f"  {len(df):,} stock descriptors inserted")

    df_etf = sh.tickers(table="SFP")
    if not df_etf.empty:
        descriptor_repo.insert_descriptors(df_etf)
        print(f"  {len(df_etf):,} ETF/fund descriptors inserted")


def load_fundamentals(sh: SharadarData) -> None:
    print("Loading fundamentals from Sharadar SF1...")
    for dim in ("ARY", "ARQ", "ART"):
        print(f"  Dimension {dim}...")
        df = sh.fundamentals(dimension=dim, start_date=START_DATE)
        if not df.empty:
            n = fund_repo.upsert_fundamentals(df)
            print(f"    {n:,} rows")
        else:
            print(f"    No data")


def load_insider(sh: SharadarData) -> None:
    print("Loading insider transactions from Sharadar SF2...")
    df = sh.insider_transactions(start_date=START_DATE)
    if not df.empty:
        n = inst_repo.upsert_insider(df)
        print(f"  {n:,} rows inserted")
    else:
        print("  No data")


def load_institutional(sh: SharadarData) -> None:
    print("Loading institutional summary from Sharadar SF3A...")
    df = sh.institutional_by_company(start_date=START_DATE)
    if not df.empty:
        n = inst_repo.upsert_institutional_summary(df)
        print(f"  {n:,} rows inserted")
    else:
        print("  No data")


def load_daily_metrics(sh: SharadarData) -> None:
    print("Loading DAILY valuation metrics from Sharadar...")
    df = sh.daily_metrics(start_date=START_DATE)
    if not df.empty:
        n = mm_repo.upsert_daily(df)
        print(f"  {n:,} rows inserted")
    else:
        print("  No data")


def load_market_metrics(sh: SharadarData) -> None:
    print("Loading METRICS (technical/risk) from Sharadar...")
    df = sh.market_metrics(start_date=START_DATE)
    if not df.empty:
        n = mm_repo.upsert_market_metrics(df)
        print(f"  {n:,} rows inserted")
    else:
        print("  No data")


def load_events(sh: SharadarData) -> None:
    print("Loading corporate events from Sharadar EVENTS...")
    df = sh.events(start_date=START_DATE)
    if not df.empty:
        n = mm_repo.upsert_events(df)
        print(f"  {n:,} rows inserted")
    else:
        print("  No data")


def load_sp500(sh: SharadarData) -> None:
    print("Loading S&P 500 constituent history from Sharadar SP500...")
    df = sh.sp500_history()
    if not df.empty:
        n = mm_repo.upsert_sp500(df)
        print(f"  {n:,} rows inserted")
    else:
        print("  No data")


def load_fund_prices(sh: SharadarData) -> None:
    print(f"Loading fund/ETF prices from Sharadar SFP ({len(SECTOR_ETFS)} ETFs + SPY)...")
    etfs = ["SPY"] + SECTOR_ETFS
    df = sh.fund_prices(tickers=etfs, start_date=START_DATE)
    if not df.empty:
        n = mm_repo.upsert_fund_prices(df)
        print(f"  {n:,} rows inserted")
    else:
        print("  No data")


if __name__ == "__main__":
    sh = SharadarData()

    print("=== QuorumNexus initial data load ===")
    print(f"Date range: {START_DATE} → {END_DATE}")
    print(f"Universe: {len(STOCK_SYMBOLS)} stocks, {len(ALL_SYMBOLS)} total symbols\n")

    load_descriptors(sh)
    load_fundamentals(sh)
    load_insider(sh)
    load_institutional(sh)
    load_daily_metrics(sh)
    load_market_metrics(sh)
    load_events(sh)
    load_sp500(sh)
    load_fund_prices(sh)

    print("\n--- Alpaca-sourced data ---")
    load_ohlcv()
    load_indicators()

    print("\n=== Load complete ===")
