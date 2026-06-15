from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.timeframe import TimeFrame
import alpaca.data.requests as DataRequest
import pandas as pd

import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ALPACA_PUBLIC_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")


def _to_alpaca(sym: str) -> str:
    return sym.replace("-", ".")


class MarketData:
    def __init__(self):
        if not API_KEY or not SECRET_KEY:
            raise ValueError("Missing Alpaca API credentials.")

        self.MarketDataClient = StockHistoricalDataClient(API_KEY, SECRET_KEY)
        self.ohlcv = pd.DataFrame()

    def get_OHLCV(
        self, symbols: list[str] | str, start_date: pd.Timestamp, end_date: pd.Timestamp
    ):
        symbols = [symbols] if isinstance(symbols, str) else symbols
        alpaca_symbols = [_to_alpaca(s) for s in symbols]
        symbol_map = {_to_alpaca(s): s for s in symbols}

        hData = DataRequest.StockBarsRequest(
            symbol_or_symbols=alpaca_symbols,
            start=pd.Timestamp(start_date),
            end=pd.Timestamp(end_date),
            sort="desc",
            timeframe=TimeFrame.Day,
            feed="iex",
        )

        raw = self.MarketDataClient.get_stock_bars(hData)

        data_list = []

        for alpaca_sym in alpaca_symbols:
            for item in raw.data[alpaca_sym]:
                data_list.append(
                    {
                        "symbol": symbol_map[item.symbol],
                        "date": item.timestamp.date(),
                        "open": item.open,
                        "high": item.high,
                        "low": item.low,
                        "close": item.close,
                        "volume": item.volume,
                    }
                )

        self.ohlcv = pd.DataFrame(data_list)
        self.ohlcv["date"] = pd.to_datetime(self.ohlcv["date"])

        return self.ohlcv


if __name__ == "__main__":
    md = MarketData()
    df = md.get_OHLCV(["AAPL", "GOOGL"], "2020-01-01", "2020-12-31")
    print(df.head(20))
