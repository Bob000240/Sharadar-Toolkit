"""
Daily incremental update script.
Run each market day after close to keep all tables current.

Sharadar data is updated daily by Nasdaq Data Link;
Alpaca OHLCV is fetched directly from the market.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from set_up.config import ALL_SYMBOLS, STOCK_SYMBOLS, BENCHMARK_SYMBOLS
from data_det.raw_data.sharadar_data import SharadarData
from data_det.raw_data.market_data import MarketData
from data_det.processed_data.indicators import compute_indicators
import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
import database.descriptors_repository as descriptor_repo
import database.fundamentals_repository as fund_repo
import database.institutional_repository as inst_repo
import database.market_metrics_repository as mm_repo

SECTOR_ETFS = [s for s in BENCHMARK_SYMBOLS if s != "SPY"]


def _latest_date_str(latest_df: pd.DataFrame, col: str = "latest_date") -> str | None:
    if latest_df.empty or col not in latest_df.columns:
        return None
    return str(latest_df[col].min())


def update_ohlcv() -> None:
    latest = market_repo.get_latest_date(ALL_SYMBOLS)
    if latest.empty:
        print("OHLCV: no data — run load_data.py first")
        return
    start = pd.Timestamp(latest["latest_date"].min()) + pd.Timedelta(days=1)
    today = pd.Timestamp.today()
    if start.date() > today.date():
        print("OHLCV: up to date")
        return
    df = MarketData().get_OHLCV(ALL_SYMBOLS, start, today)
    if not df.empty:
        market_repo.insert_OHLCV_table(df)
        print(f"OHLCV: {len(df):,} new rows")
    else:
        print("OHLCV: no new rows")


def update_indicators() -> None:
    latest = indicator_repo.get_latest_date(ALL_SYMBOLS)
    if latest.empty:
        print("Indicators: no data — run load_data.py first")
        return
    latest_date = latest["latest_date"].min()
    today = pd.Timestamp.today().date()
    if latest_date >= today:
        print("Indicators: up to date")
        return
    lookback = pd.Timestamp(latest_date) - pd.Timedelta(days=400)
    all_ohlcv = market_repo.get_OHLCV(ALL_SYMBOLS, lookback, today)
    all_ohlcv = all_ohlcv.sort_values(["symbol", "date"])
    parts = [
        compute_indicators(g.reset_index(drop=True))
        for _, g in all_ohlcv.groupby("symbol", sort=False)
    ]
    processed = pd.concat(parts, ignore_index=True)
    new_rows = processed[processed["date"] > latest_date]
    if not new_rows.empty:
        indicator_repo.insert_indicators(new_rows)
        print(f"Indicators: {len(new_rows):,} new rows")
    else:
        print("Indicators: up to date")


def update_descriptors(sh: SharadarData) -> None:
    print("Descriptors: refreshing from Sharadar TICKERS...")
    df = sh.tickers(table="SEP", is_delisted=False)
    if not df.empty:
        descriptor_repo.insert_descriptors(df)
    df_etf = sh.tickers(table="SFP")
    if not df_etf.empty:
        descriptor_repo.insert_descriptors(df_etf)
    print(f"Descriptors: {len(df) + len(df_etf):,} upserted")


def update_fundamentals(sh: SharadarData) -> None:
    """Re-fetch the last 90 days of SF1 to catch late filings."""
    since = (pd.Timestamp.today() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    total = 0
    for dim in ("ARY", "ARQ", "ART"):
        df = sh.fundamentals(dimension=dim, start_date=since)
        if not df.empty:
            total += fund_repo.upsert_fundamentals(df)
    print(f"Fundamentals: {total:,} rows upserted (last 90d)")


def update_insider(sh: SharadarData) -> None:
    """Fetch last 14 days of SF2 to catch new Form 4 filings."""
    since = (pd.Timestamp.today() - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    df = sh.insider_transactions(start_date=since)
    if not df.empty:
        n = inst_repo.upsert_insider(df)
        print(f"Insider: {n:,} rows upserted")
    else:
        print("Insider: no new filings")


def update_institutional(sh: SharadarData) -> None:
    """SF3A is quarterly — only update if a new quarter has been filed."""
    since = (pd.Timestamp.today() - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    df = sh.institutional_by_company(start_date=since)
    if not df.empty:
        n = inst_repo.upsert_institutional_summary(df)
        print(f"Institutional: {n:,} rows upserted")
    else:
        print("Institutional: no new data")


def update_daily_metrics(sh: SharadarData) -> None:
    since = (pd.Timestamp.today() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    df = sh.daily_metrics(start_date=since)
    if not df.empty:
        n = mm_repo.upsert_daily(df)
        print(f"Daily metrics: {n:,} rows upserted")
    else:
        print("Daily metrics: no new data")


def update_market_metrics(sh: SharadarData) -> None:
    since = (pd.Timestamp.today() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    df = sh.market_metrics(start_date=since)
    if not df.empty:
        n = mm_repo.upsert_market_metrics(df)
        print(f"Market metrics: {n:,} rows upserted")
    else:
        print("Market metrics: no new data")


def update_events(sh: SharadarData) -> None:
    since = (pd.Timestamp.today() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    df = sh.events(start_date=since)
    if not df.empty:
        n = mm_repo.upsert_events(df)
        print(f"Events: {n:,} rows upserted")
    else:
        print("Events: no new data")


def update_fund_prices(sh: SharadarData) -> None:
    etfs = ["SPY"] + SECTOR_ETFS
    since = (pd.Timestamp.today() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    df = sh.fund_prices(tickers=etfs, start_date=since)
    if not df.empty:
        n = mm_repo.upsert_fund_prices(df)
        print(f"Fund prices: {n:,} rows upserted")
    else:
        print("Fund prices: no new data")


if __name__ == "__main__":
    sh = SharadarData()
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    print(f"=== QuorumNexus daily update — {today} ===")

    update_ohlcv()
    update_indicators()
    update_fundamentals(sh)
    update_insider(sh)
    update_daily_metrics(sh)
    update_market_metrics(sh)
    update_events(sh)
    update_fund_prices(sh)

    # Weekly refreshes (run every day — all are upsert-safe)
    update_descriptors(sh)
    update_institutional(sh)

    print("=== Done ===")
