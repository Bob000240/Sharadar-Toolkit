"""
Initial full data load. Run once after setup_db.py.

    uv run python -m set_up.load_data
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from set_up.config import STOCK_SYMBOLS, BENCHMARK_SYMBOLS
from data.sharadar_data import SharadarData
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

START_DATE = "2021-01-01"
END_DATE = pd.Timestamp.today().strftime("%Y-%m-%d")


def load_tickers(sh: SharadarData):
    print("Loading tickers...")
    equities = sh.tickers(table="SEP", is_delisted=False)
    funds = sh.tickers(table="SFP", tickers=BENCHMARK_SYMBOLS)
    df = pd.concat([equities, funds], ignore_index=True)
    tickers_repo.insert(df)
    print(f"  {len(df):,} rows")


def _batched(sh_fn, repo_insert, label: str, symbols: list = None, batch_size: int = 50, **kwargs):
    symbols = symbols or STOCK_SYMBOLS
    total = 0
    n_batches = -(-len(symbols) // batch_size)
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        df = sh_fn(tickers=batch, **kwargs)
        if not df.empty:
            repo_insert(df)
            total += len(df)
        print(f"  {label} batch {i // batch_size + 1}/{n_batches}: {len(df):,} rows")
    print(f"  {label} total: {total:,} rows")


def load_equity_prices(sh: SharadarData):
    print("Loading equity prices (SEP)...")
    _batched(sh.equity_prices, equity_repo.insert, "SEP",
             start_date=START_DATE, end_date=END_DATE)


def load_fund_prices(sh: SharadarData):
    print("Loading fund prices (SFP)...")
    _batched(sh.fund_prices, fund_repo.insert, "SFP",
             symbols=BENCHMARK_SYMBOLS, start_date=START_DATE, end_date=END_DATE)


def load_indicators():
    print("Computing indicators from equity prices...")
    total = 0
    for i in range(0, len(STOCK_SYMBOLS), 50):
        batch = STOCK_SYMBOLS[i:i + 50]
        df = equity_repo.get(tickers=batch, start_date=START_DATE)
        if df.empty:
            continue
        parts = [
            compute_indicators(g.reset_index(drop=True))
            for _, g in df.sort_values(["ticker", "date"]).groupby("ticker", sort=False)
        ]
        ind_df = pd.concat(parts, ignore_index=True)
        indicators_repo.insert(ind_df)
        total += len(ind_df)
        print(f"  batch {i // 50 + 1}/{-(-len(STOCK_SYMBOLS) // 50)}: {len(ind_df):,} rows")
    print(f"  total: {total:,} rows")


def load_fundamentals(sh: SharadarData):
    print("Loading fundamentals (SF1)...")
    for dim in ("ARY", "ARQ", "ART"):
        _batched(sh.fundamentals, fundamentals_repo.insert, dim,
                 dimension=dim, start_date=START_DATE, end_date=END_DATE)


def load_insider(sh: SharadarData):
    print("Loading insider transactions (SF2)...")
    _batched(sh.insider_transactions, insider_repo.insert, "SF2",
             start_date=START_DATE, end_date=END_DATE)


def load_institutional(sh: SharadarData):
    print("Loading institutional holdings (SF3)...")
    _batched(sh.institutional_holdings, institutional_repo.insert, "SF3",
             start_date=START_DATE, end_date=END_DATE)


def load_events(sh: SharadarData):
    print("Loading events (EVENTS)...")
    _batched(sh.events, event_repo.insert, "EVENTS",
             start_date=START_DATE, end_date=END_DATE)


def load_macro():
    print("Loading macro data (FRED)...")
    df = MacroData().get_macro(START_DATE, END_DATE)
    macro_repo.insert(df)
    print(f"  {len(df):,} rows")


if __name__ == "__main__":
    print(f"=== QuorumNexus initial data load ===")
    print(f"Date range: {START_DATE} → {END_DATE}")
    print(f"Universe: {len(STOCK_SYMBOLS)} stocks, {len(BENCHMARK_SYMBOLS)} ETFs\n")

    sh = SharadarData()

    load_tickers(sh)
    load_equity_prices(sh)
    load_fund_prices(sh)
    load_indicators()
    load_fundamentals(sh)
    load_insider(sh)
    load_institutional(sh)
    load_events(sh)
    load_macro()

    print("\n=== Load complete ===")
