import os
import time
import requests
import pandas as pd
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

    def _ttm(self, endpoint: str, syms: list[str]) -> pd.DataFrame:
        """Fetch a TTM endpoint that returns a single row per symbol."""
        rows = []
        for s in syms:
            data = self._fetch(endpoint, symbol=s)
            if data:
                rows.append({**data[0], "symbol": s})
        return pd.DataFrame(rows)

    # -------------------------------------------------------------------------
    # Financial Statements
    # -------------------------------------------------------------------------

    def income(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("income-statement", sym, period=period, limit=limit))

    def balance(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("balance-sheet-statement", sym, period=period, limit=limit))

    def cashflow(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("cash-flow-statement", sym, period=period, limit=limit))

    # -------------------------------------------------------------------------
    # Financial Statements TTM
    # -------------------------------------------------------------------------

    def income_ttm(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return self._ttm("income-statement-ttm", sym)

    def balance_ttm(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return self._ttm("balance-sheet-statement-ttm", sym)

    def cashflow_ttm(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return self._ttm("cash-flow-statement-ttm", sym)

    # -------------------------------------------------------------------------
    # Ratios
    # -------------------------------------------------------------------------

    def key_metrics(self, sym: str | list[str], limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("key-metrics", sym, period="annual", limit=limit))

    def key_metrics_ttm(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return self._ttm("key-metrics-ttm", sym)

    def ratios(self, sym: str | list[str], limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("ratios", sym, period="annual", limit=limit))

    def ratios_ttm(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return self._ttm("ratios-ttm", sym)

    # -------------------------------------------------------------------------
    # Analysis
    # -------------------------------------------------------------------------

    def owner_earnings(self, sym: str | list[str], limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("owner-earnings", sym, limit=limit))

    def enterprise_values(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("enterprise-values", sym, period=period, limit=limit))

    # -------------------------------------------------------------------------
    # Growth
    # -------------------------------------------------------------------------

    def income_growth(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("income-statement-growth", sym, period=period, limit=limit))

    def balance_growth(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("balance-sheet-statement-growth", sym, period=period, limit=limit))

    def cashflow_growth(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("cash-flow-statement-growth", sym, period=period, limit=limit))

    def financial_growth(self, sym: str | list[str], period: str = "annual", limit: int = 10) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("financial-growth", sym, period=period, limit=limit))

    # -------------------------------------------------------------------------
    # Formats / SEC Filings
    # -------------------------------------------------------------------------

    def financial_report_dates(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("financial-reports-dates", sym))

    def financial_report_json(self, sym: str, year: int, period: str = "FY") -> dict:
        """period: FY | Q1 | Q2 | Q3 | Q4"""
        data = self._fetch("financial-reports-json", symbol=sym, year=year, period=period)
        return data[0] if data else {}

    # -------------------------------------------------------------------------
    # Segmentation
    # -------------------------------------------------------------------------

    def revenue_product_segmentation(self, sym: str | list[str], period: str = "annual") -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("revenue-product-segmentation", sym, period=period))

    def revenue_geographic_segmentation(self, sym: str | list[str], period: str = "annual") -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("revenue-geographic-segmentation", sym, period=period))

    # -------------------------------------------------------------------------
    # Other (kept from original)
    # -------------------------------------------------------------------------

    def profile(self, sym: str | list[str]) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("profile", sym))

    def analyst_estimates(self, sym: str | list[str], limit: int = 2) -> pd.DataFrame:
        sym = [sym] if isinstance(sym, str) else sym
        return pd.DataFrame(self._fetch_multi("analyst-estimates", sym, period="annual", limit=limit))



if __name__ == "__main__":
    fd = FundamentalsData(["AAPL"])
    sym = "AAPL"

    checks = [
        ("income (annual)",                  lambda: fd.income(sym)),
        ("balance (annual)",                 lambda: fd.balance(sym)),
        ("cashflow (annual)",                lambda: fd.cashflow(sym)),
        ("latest_statements",                lambda: fd.latest_statements(sym)),
        ("income_ttm",                       lambda: fd.income_ttm(sym)),
        ("balance_ttm",                      lambda: fd.balance_ttm(sym)),
        ("cashflow_ttm",                     lambda: fd.cashflow_ttm(sym)),
        ("key_metrics (annual)",             lambda: fd.key_metrics(sym)),
        ("key_metrics_ttm",                  lambda: fd.key_metrics_ttm(sym)),
        ("ratios (annual)",                  lambda: fd.ratios(sym)),
        ("ratios_ttm",                       lambda: fd.ratios_ttm(sym)),
        ("owner_earnings",                   lambda: fd.owner_earnings(sym)),
        ("enterprise_values",                lambda: fd.enterprise_values(sym)),
        ("income_growth (annual)",           lambda: fd.income_growth(sym)),
        ("balance_growth (annual)",          lambda: fd.balance_growth(sym)),
        ("cashflow_growth (annual)",         lambda: fd.cashflow_growth(sym)),
        ("financial_growth (annual)",        lambda: fd.financial_growth(sym)),
        ("financial_report_dates",           lambda: fd.financial_report_dates(sym)),
        ("revenue_product_segmentation",     lambda: fd.revenue_product_segmentation(sym)),
        ("revenue_geographic_segmentation",  lambda: fd.revenue_geographic_segmentation(sym)),
        ("profile",                          lambda: fd.profile(sym)),
        ("analyst_estimates",                lambda: fd.analyst_estimates(sym)),
    ]

    for name, fn in checks:
        try:
            df = fn()
            print(f"\n=== {name} ===")
            print(list(df.columns) if not df.empty else "  (empty)")
        except Exception as e:
            print(f"\n=== {name} ===")
            print(f"  ERROR: {e}")