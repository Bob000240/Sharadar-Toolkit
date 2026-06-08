from data_collection.market_data import MarketData
from data_collection.sector_data import get_sector
from data_collection.fundamentals_data import FundamentalsData
from refined_data.fundamentals_transform import build_quality, build_value, build_growth
from refined_data.indicators import compute_indicators
import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
import database.sector_repository as sector_repo
import database.fundamentals_repository as fund_repo
import pandas as pd
from config import ALL_SYMBOLS, STOCK_SYMBOLS, BENCHMARK_SYMBOLS


def update_market_data():
    today      = pd.Timestamp.today()
    latest_df  = market_repo.get_latest_date(ALL_SYMBOLS)
    latest_map = dict(zip(latest_df["symbol"], pd.to_datetime(latest_df["latest_date"])))

    if not latest_map:
        print("No existing market data — run main.py for initial load")
        return

    start = min(latest_map.values()) + pd.Timedelta(days=1)
    if start.date() > today.date():
        print("Market data already up to date")
        return

    end = today + pd.Timedelta(days=1)
    df = MarketData().get_OHLCV(ALL_SYMBOLS, start, end)
    if not df.empty:
        market_repo.insert_OHLCV_table(df)
        print(f"Market data: inserted {len(df)} new rows")


def update_indicators():
    today      = pd.Timestamp.today()
    latest_df  = indicator_repo.get_latest_date(ALL_SYMBOLS)
    latest_map = dict(zip(latest_df["symbol"], pd.to_datetime(latest_df["latest_date"])))

    for sym in ALL_SYMBOLS:
        sym_latest = latest_map.get(sym)
        if sym_latest is not None and sym_latest.date() >= today.date():
            continue

        # Fetch enough history for the longest lookback (252-day return)
        lookback_start = today - pd.Timedelta(days=300)
        df = market_repo.get_OHLCV(sym, lookback_start, today)
        if df.empty:
            continue

        df = compute_indicators(df)

        if sym_latest is not None:
            df = df[df["date"] > sym_latest]

        if not df.empty:
            indicator_repo.insert_indicators(df)

    print("Indicators updated")


def update_fundamentals_full():
    """Re-fetch quality, value, and growth (annual/quarterly filings). Run after earnings season."""
    fd = FundamentalsData(STOCK_SYMBOLS)
    fund_repo.insert_quality(build_quality(fd))
    fund_repo.insert_value(build_value(fd))
    fund_repo.insert_growth(build_growth(fd))
    print("Full fundamentals updated")


if __name__ == "__main__":
    print("=== Daily update ===")
    update_market_data()
    update_indicators()
    print("=== Done ===")
