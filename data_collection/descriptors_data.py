import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://financialmodelingprep.com/stable"
_REQUEST_DELAY = 0.25

SECTOR_ETF_MAPPING = {
    "XLK":  "Technology",
    "XLV":  "Healthcare",
    "XLF":  "Financial Services",
    "XLY":  "Consumer Cyclical",
    "XLP":  "Consumer Defensive",
    "XLE":  "Energy",
    "XLU":  "Utilities",
    "XLI":  "Industrials",
    "XLB":  "Basic Materials",
    "XLRE": "Real Estate",
    "XLC":  "Communication Services",
}


def _size_bucket(market_cap: float | None) -> str:
    if market_cap is None:
        return "Unknown"
    if market_cap >= 200_000_000_000:
        return "Mega"
    if market_cap >= 10_000_000_000:
        return "Large"
    if market_cap >= 2_000_000_000:
        return "Mid"
    if market_cap >= 300_000_000:
        return "Small"
    return "Micro"


class DescriptorsData:
    def __init__(self, symbols: str | list[str]):
        self.symbols = [symbols] if isinstance(symbols, str) else symbols
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            raise ValueError("FMP_API_KEY not set in environment.")
        self._key = api_key
        self._session = requests.Session()
        self._cache: dict[str, dict] = {}

    def _fetch_profile(self, symbol: str) -> dict:
        if symbol in self._cache:
            return self._cache[symbol]

        time.sleep(_REQUEST_DELAY)
        r = self._session.get(
            f"{BASE_URL}/profile",
            params={"symbol": symbol, "apikey": self._key},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        result = data[0] if isinstance(data, list) and data else {}
        self._cache[symbol] = result
        return result

    def profile(self, symbol: str) -> dict:
        return self._fetch_profile(symbol)

    def get_descriptors(self) -> pd.DataFrame:
        records = []
        for sym in self.symbols:
            if sym in SECTOR_ETF_MAPPING:
                records.append({
                    "symbol":      sym,
                    "company_name": sym,
                    "sector":      SECTOR_ETF_MAPPING[sym],
                    "industry":    "ETF",
                    "country":     "US",
                    "exchange":    "NYSE",
                    "currency":    "USD",
                    "market_cap":  None,
                    "size_bucket": "ETF",
                    "is_etf":      True,
                })
                continue

            try:
                p = self._fetch_profile(sym)
                market_cap = p.get("marketCap")
                if market_cap is not None:
                    try:
                        market_cap = float(market_cap)
                    except (TypeError, ValueError):
                        market_cap = None

                records.append({
                    "symbol":       sym,
                    "company_name": p.get("companyName", sym),
                    "sector":       p.get("sector") or "Unknown",
                    "industry":     p.get("industry") or "Unknown",
                    "country":      p.get("country") or "Unknown",
                    "exchange":     p.get("exchangeShortName") or p.get("exchange") or "Unknown",
                    "currency":     p.get("currency") or "USD",
                    "market_cap":   market_cap,
                    "size_bucket":  _size_bucket(market_cap),
                    "is_etf":       bool(p.get("isEtf", False)),
                })
            except Exception as e:
                print(f"Failed to fetch descriptors for {sym}: {e}")
                records.append({
                    "symbol":       sym,
                    "company_name": sym,
                    "sector":       "Unknown",
                    "industry":     "Unknown",
                    "country":      "Unknown",
                    "exchange":     "Unknown",
                    "currency":     "USD",
                    "market_cap":   None,
                    "size_bucket":  "Unknown",
                    "is_etf":       False,
                })

        return pd.DataFrame(records)


if __name__ == "__main__":
    symbols = ["AAPL", "MSFT", "NVDA", "INTC", "XLK", "GME"]
    d = DescriptorsData(symbols)
    df = d.get_descriptors()
    print(df.to_string())
