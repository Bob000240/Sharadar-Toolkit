from data_collection.market_data import MarketData
import derived_features.indicators as indicators
import database.market_data_repository as market_repo
import database.indicator_repository as indicator_repo

if __name__ == "__main__":
    symbol = "AAPL"
    start_date = "2026-02-01"
    end_date = "2026-04-30"

    market_repo.drop_OHLCV_table()
    market_repo.create_OHLCV_table()
    market_repo.insert_OHLCV_table(MarketData().get_OHLCV(symbol, start_date, end_date))

    indicator_repo.drop_indicators_table()
    indicator_repo.create_indicators_table()
    df = market_repo.get_OHLCV(symbol, start_date, end_date)
    df = indicators.compute_trading_indicators(df)
    indicator_repo.insert_indicators(df)

    df_check = indicator_repo.get_indicators(symbol, start_date, end_date)
    print(df_check.sort_values("date", ascending=False).head())