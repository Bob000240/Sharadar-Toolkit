from data_collection.market_data import MarketData
from data_collection.descriptors_data import DescriptorsData
from data_collection.fundamentals_data import FundamentalsData
from processed_data.fundamentals_transform import build_quality, build_value, build_growth
from processed_data.indicators import compute_indicators
from config import ALL_SYMBOLS, STOCK_SYMBOLS, BENCHMARK_SYMBOLS
import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
import database.descriptors_repository as descriptor_repo
import database.fundamentals_repository as fund_repo
import pandas as pd

if __name__ == "__main__":
    start_date = "2025-01-01"
    end_date   = pd.Timestamp.today()

    market_repo.drop_OHLCV_table()
    market_repo.create_OHLCV_table()
    market_repo.insert_OHLCV_table(
        MarketData().get_OHLCV(ALL_SYMBOLS, start_date, end_date)
    )

    indicator_repo.drop_indicators_table()
    indicator_repo.create_indicators_table()

    descriptor_repo.drop_descriptors_table()
    descriptor_repo.create_descriptors_table()

    for symbol in ALL_SYMBOLS:
        print(f"Processing {symbol}")

        df = market_repo.get_OHLCV(symbol, start_date, end_date)
        df = compute_indicators(df)

        if "symbol" not in df.columns:
            print(f"ERROR: symbol column missing for {symbol}")
            print(df.columns)
            break

        if df["symbol"].isna().any():
            print(f"ERROR: symbol contains NaN for {symbol}")
            break

        indicator_repo.insert_indicators(df)

    descriptor_repo.insert_descriptors(DescriptorsData(ALL_SYMBOLS).get_descriptors())

    # fund_repo.drop_fundamentals_tables()
    # fund_repo.create_fundamentals_tables()

    # fd = FundamentalsData(STOCK_SYMBOLS)
    # fund_repo.insert_quality(build_quality(fd))
    # fund_repo.insert_growth(build_growth(fd))
    # fund_repo.insert_value(build_value(fd))

    pd.set_option("display.max_columns", None)
    df = market_repo.get_OHLCV(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = indicator_repo.get_indicators(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = descriptor_repo.get_descriptors(["SPY", "AAPL"])
    print(df)
    df = fund_repo.get_quality(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = fund_repo.get_growth(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = fund_repo.get_value(["SPY", "AAPL"], start_date,end_date)
    print(df.sort_values("date", ascending=False).head())
