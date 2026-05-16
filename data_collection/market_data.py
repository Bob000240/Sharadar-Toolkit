from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.timeframe import TimeFrame
import alpaca.data.requests as DataRequest
from datetime import datetime, timedelta
import pandas as pd

import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ALPACA_PUBLIC_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

class MarketData:
    def __init__(self):
        if not API_KEY or not SECRET_KEY:
            raise ValueError("Missing Alpaca API credentials.")
        self.MarketDataClient = StockHistoricalDataClient(API_KEY, SECRET_KEY)
        self.ohlcv = pd.DataFrame()

    def get_OHLCV(self, symbol, start_date, end_date):
        hData = DataRequest.StockBarsRequest(
            symbol_or_symbols = symbol,
            start = start_date,
            end = end_date,
            #limit = 100,
            # currency: SupportedCurrencies | None = None,
            sort = "desc",
            timeframe = TimeFrame.Day,
            # adjustment: Adjustment | None = None,
            # feed: DataFeed | None = None,
            # asof: str | None = None
        )
        raw = self.MarketDataClient.get_stock_bars(hData)  
        data_list = []
        for item in raw[symbol]:
            data_list.append({
                "symbol": item.symbol,
                "date": item.timestamp.date(),
                "open": item.open,
                "high": item.high,
                "low": item.low,
                "close": item.close,
                "volume": item.volume,
            })
        self.ohlcv = pd.DataFrame(data_list)
        return self.ohlcv
