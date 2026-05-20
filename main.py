from data_collection.market_data import MarketData
from data_collection.sector_data import sector_mapping
from derived_features.indicators import compute_indicators
import database.market_data_repository as market_repo
import database.indicator_repository as indicator_repo
import database.sector_data_repository as sector_repo
import pandas as pd

if __name__ == "__main__":
    symbols = [
        "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT",
        "GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ",
        "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "COST", "WMT",
        "JPM", "BAC", "GS", "MS", "WFC", "BLK", "V", "MA",
        "LLY", "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO",
        "CAT", "BA", "HON", "GE", "UPS",
        "XOM", "CVX",
        "SPY"
    ]
    start_date = "2016-01-01"
    end_date = pd.Timestamp.today()
    
    market_repo.drop_OHLCV_table()
    market_repo.create_OHLCV_table()
    market_repo.insert_OHLCV_table(MarketData().get_OHLCV(symbols, start_date, end_date))
    
    indicator_repo.drop_indicators_table()
    indicator_repo.create_indicators_table()

    sector_repo.drop_sector_mapping_table()
    sector_repo.create_sector_mapping_table()

    for symbol in symbols:
        df = market_repo.get_OHLCV(symbol, start_date, end_date)
        df = compute_indicators(df)
        indicator_repo.insert_indicators(df)

    
    sector_repo.insert_sector_mapping(sector_mapping(symbols))

    df = market_repo.get_OHLCV(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = indicator_repo.get_indicators(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = sector_repo.get_sector_mapping(["SPY", "AAPL"])
    print(df)

