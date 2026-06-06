import os
import time
import requests
import pandas as pd
from datetime import date as date_cls
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://financialmodelingprep.com/stable"

_REQUEST_DELAY = 0.25  # seconds between requests to stay under rate limits

class FundamentalsData:
    def __init__(self, symbols: str | list[str]):
        self.symbols = [symbols] if isinstance(symbols, str) else symbols
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            raise ValueError("FMP_API_KEY not set in environment.")
        self._key = api_key
        self._session = requests.Session()
        self._cache: dict[str, list] = {}

    def _fetch(self, endpoint: str, **params) -> list[dict]:
        cache_key = f"{endpoint},{sorted(params.items())}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{BASE_URL}/{endpoint}"
        req_params = {**params, "apikey": self._key}
        backoff = 1.0
        for attempt in range(5):
            time.sleep(_REQUEST_DELAY)
            r = self._session.get(url, params=req_params, timeout=30)
            if r.status_code == 429:
                print(f"Rate limited on {endpoint} (attempt {attempt + 1}), retrying in {backoff:.0f}s…")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            r.raise_for_status()
            break
        else:
            r.raise_for_status()

        data = r.json()
        if isinstance(data, dict):
            if msg := data.get("Error Message"):
                raise RuntimeError(f"FMP error ({endpoint}): {msg}")
            data = []
        self._cache[cache_key] = data
        return data

    def _fetch_multi(self, endpoint: str, syms: list[str], **params) -> list[dict]:
        rows = []
        for s in syms:
            rows.extend(self._fetch(endpoint, symbol=s, **params))
        return rows

    def income(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("income-statement", sym, period=period, limit=limit))

    def balance(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("balance-sheet-statement", sym, period=period, limit=limit))

    def cashflow(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("cash-flow-statement", sym, period=period, limit=limit))

    def key_metrics(self, sym: str | list[str], limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("key-metrics", sym, period="annual", limit=limit))

    def key_metrics_ttm(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        rows = []
        for s in sym:
            data = self._fetch("key-metrics-ttm", symbol=s)
            if data:
                rows.append(data[0])
        return pd.DataFrame(rows)

    def ratios(self, sym: str | list[str], limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("ratios", sym, period="annual", limit=limit))

    def profile(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("profile", sym))

    def financial_growth(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("financial-growth", sym, period=period, limit=limit))

    def analyst_estimates(self, sym: str | list[str], limit: int = 2) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("analyst-estimates", sym, period="annual", limit=limit))

"""
if __name__ == "__main__":
    symbols = ["AAPL", "MSFT", "NVDA","QQQ"]
    fd = FundamentalsData(symbols)
    print(fd.income(symbols))
    print(fd.balance(symbols))
    print(fd.cashflow(symbols))
    print(fd.key_metrics(symbols))
    print(fd.key_metrics_ttm(symbols))
    print(fd.ratios(symbols))
    print(fd.profile(symbols))
    print(fd.financial_growth(symbols, period="quarter"))
    print(fd.financial_growth(symbols, period="annual"))
    print(fd.analyst_estimates(symbols))

"""
