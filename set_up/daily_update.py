import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_det.raw_data.market_data import MarketData
from data_det.raw_data.descriptors_data import DescriptorsData
from data_det.raw_data.fundamentals_data import FundamentalsData
from data_det.processed_data.fundamentals_transform import build_quality, build_value, build_growth
from data_det.processed_data.indicators import compute_indicators
import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
import database.descriptors_repository as descriptor_repo
import database.fundamentals_repository as fund_repo
import pandas as pd
from set_up.config import ALL_SYMBOLS, STOCK_SYMBOLS


def update_market_data():
    latest = market_repo.get_latest_date(ALL_SYMBOLS)
    if latest.empty:
        print("No market data — run main.py for initial load")
        return
    start = pd.Timestamp(latest["latest_date"].min()) + pd.Timedelta(days=1)
    today = pd.Timestamp.today()
    if start.date() > today.date():
        print("Market data already up to date")
        return
    df = MarketData().get_OHLCV(ALL_SYMBOLS, start, today)
    if not df.empty:
        market_repo.insert_OHLCV_table(df)
        print(f"Market data: {len(df)} new rows")


def update_indicators():
    latest = indicator_repo.get_latest_date(ALL_SYMBOLS)
    if latest.empty:
        print("No indicator data — run main.py for initial load")
        return
    latest_date = latest["latest_date"].min()
    today = pd.Timestamp.today().date()
    if latest_date >= today:
        print("Indicators already up to date")
        return
    lookback_start = pd.Timestamp(latest_date) - pd.Timedelta(days=400)
    all_ohlcv = market_repo.get_OHLCV(ALL_SYMBOLS, lookback_start, today)
    all_ohlcv = all_ohlcv.sort_values(["symbol", "date"])
    processed = pd.concat(
        [compute_indicators(df.reset_index(drop=True)) for _, df in all_ohlcv.groupby("symbol", sort=False)],
        ignore_index=True,
    )
    new_rows = processed[processed["date"] > latest_date]
    if not new_rows.empty:
        indicator_repo.insert_indicators(new_rows)
    print("Indicators updated")



def update_descriptors():
    """Refresh sector, size bucket, and market cap. Run weekly or when symbols change."""
    df = DescriptorsData(ALL_SYMBOLS).get_descriptors()
    descriptor_repo.insert_descriptors(df)
    print(f"Descriptors updated: {len(df)} symbols")


def update_fundamentals_full():
    """Re-fetch quality, value, and growth. Run quarterly after earnings season."""
    fd = FundamentalsData(STOCK_SYMBOLS)
    fund_repo.insert_quality(build_quality(fd))
    fund_repo.insert_value(build_value(fd))
    fund_repo.insert_growth(build_growth(fd))
    print("Fundamentals updated")


if __name__ == "__main__":
    print("=== Daily update ===")
    update_market_data()
    update_indicators()
    print("=== Done ===")
