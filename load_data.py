"""One-time initial data load.

Prerequisite: the schema must already exist. Apply migrations first:

    alembic upgrade head

This script then populates the (empty) tables from the upstream data sources.
It is destructive only in that it fetches and inserts large amounts of data;
the inserts themselves are idempotent (`ON CONFLICT DO NOTHING`).
"""
from config import STOCK_SYMBOLS, ALL_SYMBOLS
from raw_data.market_data import MarketData
from raw_data.descriptors_data import DescriptorsData
from raw_data.fundamentals_data import FundamentalsData
from processed_data.fundamentals_transform import build_quality, build_value, build_growth
from processed_data.indicators import compute_indicators
import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
import database.descriptors_repository as descriptor_repo
import database.fundamentals_repository as fund_repo
import pandas as pd


def load_market_and_indicators(start_date, end_date) -> None:
    market_repo.insert_OHLCV_table(
        MarketData().get_OHLCV(ALL_SYMBOLS, start_date, end_date)
    )
    for symbol in ALL_SYMBOLS:
        print(f"Processing {symbol}")
        df = market_repo.get_OHLCV(symbol, start_date, end_date)
        df = compute_indicators(df)
        if "symbol" not in df.columns or df["symbol"].isna().any():
            print(f"ERROR: bad symbol column for {symbol}")
            continue
        indicator_repo.insert_indicators(df)


def load_descriptors() -> None:
    descriptor_repo.insert_descriptors(DescriptorsData(ALL_SYMBOLS).get_descriptors())


def load_fundamentals() -> None:
    fd = FundamentalsData(STOCK_SYMBOLS)
    fund_repo.insert_quality(build_quality(fd))
    print("Inserted quality data")
    fund_repo.insert_growth(build_growth(fd))
    print("Inserted growth data")
    fund_repo.insert_value(build_value(fd))
    print("Inserted value data")


def main() -> None:
    start_date = "2025-01-01"
    end_date = pd.Timestamp.today()

    load_market_and_indicators(start_date, end_date)
    load_descriptors()
    load_fundamentals()
    print("Initial load complete.")


if __name__ == "__main__":
    main()
