import yfinance as yf
import pandas as pd

SECTOR_ETF_MAPPING = {
    "XLK": "Technology",
    "XLV": "Healthcare",
    "XLF": "Financial Services",
    "XLY": "Consumer Cyclical",
    "XLP": "Consumer Defensive",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLI": "Industrials",
    "XLB": "Basic Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


def get_sector(symbols: list[str]) -> pd.DataFrame:
    records = []
    for symbol in symbols:
        if symbol in SECTOR_ETF_MAPPING:
            records.append(
                {
                    "symbol": symbol,
                    "sector": SECTOR_ETF_MAPPING[symbol],
                    "industry": "ETF",
                }
            )
            continue

        try:
            info = yf.Ticker(symbol).info

            records.append(
                {
                    "symbol": symbol,
                    "sector": info.get("sector", "Unknown"),
                    "industry": info.get("industry", "Unknown"),
                }
            )

        except Exception as e:
            print(f"Failed to fetch sector data for {symbol}: {e}")

            records.append(
                {"symbol": symbol, "sector": "Unknown", "industry": "Unknown"}
            )

    return pd.DataFrame(records)
