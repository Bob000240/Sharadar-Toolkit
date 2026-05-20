import yfinance as yf
import pandas as pd

def sector_mapping(symbols: list[str]) -> pd.DataFrame:
    records = []
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        records.append({
            "symbol": symbol,
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown")
        })
    return pd.DataFrame(records)

if __name__ == "__main__":
    symbols = ["AAPL", "MSFT", "GOOGL"]  # Example stock symbols
    sm = sector_mapping(symbols)
    print(sm)