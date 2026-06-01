import os
import requests
import pandas as pd
from datetime import date as date_cls
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://financialmodelingprep.com/stable"

QUALITY_S = [
    "roe", "roa", "roic",
    "gross_margin", "operating_margin", "net_margin", "fcf_margin",
    "cash_conversion", "accruals_ratio",
    "debt_to_equity", "net_debt_to_ebitda", "interest_coverage",
    "current_ratio", "asset_turnover",
]

VALUE_S = [
    "pe_ratio", "forward_pe", "peg_ratio", "earnings_yield",
    "pb_ratio", "p_tangible_book",
    "ev_ebitda", "ev_sales", "ev_fcf",
    "price_to_fcf", "fcf_yield",
    "dividend_yield", "buyback_yield", "shareholder_yield",
]

GROWTH_S = [
    "revenue_growth_yoy", "eps_growth_yoy",
    "revenue_growth_qoq", "eps_growth_qoq",
    #"eps_revision_3m"
    #"revenue_vs_sector_growth",
]


def _div(num, den) -> float | None:
    try:
        if num is None or den is None or float(den) == 0:
            return None
        return float(num) / float(den)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _f(d: dict | None, *keys: str) -> float | None:
    """Extract the first non-null numeric value from a dict by trying multiple keys."""
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                f = float(v)
                if f == f:  # reject NaN
                    return f
            except (TypeError, ValueError):
                pass
    return None


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
        cache_key = f"{endpoint}|{sorted(params.items())}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        r = self._session.get(
            f"{BASE_URL}/{endpoint}",
            params={**params, "apikey": self._key},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            if msg := data.get("Error Message"):
                raise RuntimeError(f"FMP error ({endpoint}): {msg}")
            data = []
        self._cache[cache_key] = data
        return data

    def _income(self, sym: str, period: str = "annual", limit: int = 10) -> list[dict]:
        return self._fetch("income-statement", symbol=sym, period=period, limit=limit)

    def _balance(self, sym: str, period: str = "annual", limit: int = 10) -> list[dict]:
        return self._fetch("balance-sheet-statement", symbol=sym, period=period, limit=limit)

    def _cashflow(self, sym: str, period: str = "annual", limit: int = 10) -> list[dict]:
        return self._fetch("cash-flow-statement", symbol=sym, period=period, limit=limit)

    def _key_metrics(self, sym: str, limit: int = 10) -> list[dict]:
        return self._fetch("key-metrics", symbol=sym, period="annual", limit=limit)

    def _key_metrics_ttm(self, sym: str) -> dict:
        data = self._fetch("key-metrics-ttm", symbol=sym)
        return data[0] if data else {}

    def _ratios(self, sym: str, limit: int = 10) -> list[dict]:
        return self._fetch("ratios", symbol=sym, period="annual", limit=limit)

    def _profile(self, sym: str) -> dict:
        data = self._fetch("profile", symbol=sym)
        return data[0] if data else {}

    def _financial_growth(self, sym: str, period: str = "annual", limit: int = 10) -> list[dict]:
        return self._fetch("financial-growth", symbol=sym, period=period, limit=limit)

    def _analyst_estimates(self, sym: str, limit: int = 2) -> list[dict]:
        return self._fetch("analyst-estimates", symbol=sym, period="annual", limit=limit)

    # --- Public getters — each returns a DataFrame ready for DB insertion ---

    def get_quality(self) -> pd.DataFrame:
        rows = []
        for sym in self.symbols:
            inc_list = self._income(sym)
            bal_list = self._balance(sym)
            cf_list  = self._cashflow(sym)
            km_list  = self._key_metrics(sym)
            fr_list  = self._ratios(sym)

            if not inc_list:
                continue

            # Index statements by date so key-metrics / ratios align correctly
            # even when list lengths differ across endpoints.
            bal_by_date = {d.get("date", "")[:10]: d for d in bal_list}
            cf_by_date  = {d.get("date", "")[:10]: d for d in cf_list}
            km_by_date  = {d.get("date", "")[:10]: d for d in km_list}
            fr_by_date  = {d.get("date", "")[:10]: d for d in fr_list}

            bal_dates = sorted(bal_by_date)  # ascending, for prev-year lookup

            for ic in inc_list:
                date_str = ic.get("date", "")[:10]
                bc = bal_by_date.get(date_str)
                cc = cf_by_date.get(date_str)
                km = km_by_date.get(date_str)
                fr = fr_by_date.get(date_str)

                # Previous balance sheet: nearest date strictly before this one
                earlier = [d for d in bal_dates if d < date_str]
                bp = bal_by_date[earlier[-1]] if earlier else None

                # Raw statement values (needed for accruals + interest coverage)
                net_inc    = _f(ic, "netIncome")
                int_exp    = _f(ic, "interestExpense")
                ebit       = _f(ic, "ebit")
                revenue    = _f(ic, "revenue")
                cfo        = _f(cc, "operatingCashFlow")
                fcf        = _f(cc, "freeCashFlow")
                tot_assets = _f(bc, "totalAssets")
                a1         = _f(bp, "totalAssets") if bp else None
                avg_assets = _div((tot_assets or 0) + (a1 or 0), 2) if tot_assets and a1 else None

                # interest_coverage: FMP reports 0 when interestExpense == 0 (wrong).
                # None is correct when a company has no interest expense.
                int_cov = _div(ebit, abs(int_exp) if int_exp else None)

                rows.append({
                    "symbol":             sym,
                    "date":               ic.get("date", "")[:10],
                    # From FMP key-metrics (pre-computed per their definitions)
                    "roe":                _f(km, "returnOnEquity"),
                    "roa":                _f(km, "returnOnAssets"),
                    "roic":               _f(km, "returnOnInvestedCapital"),
                    "net_debt_to_ebitda": _f(km, "netDebtToEBITDA"),
                    "current_ratio":      _f(km, "currentRatio"),
                    # From FMP financial-ratios (debtToEquityRatio uses totalDebt)
                    "gross_margin":       _f(fr, "grossProfitMargin"),
                    "operating_margin":   _f(fr, "ebitMargin"),
                    "net_margin":         _f(fr, "netProfitMargin"),
                    "debt_to_equity":     _f(fr, "debtToEquityRatio"),
                    "asset_turnover":     _f(fr, "assetTurnover"),
                    # Computed from raw statements
                    "fcf_margin":         _div(fcf, revenue),
                    "cash_conversion":    _div(fcf, net_inc),   # FCF/NI per spec
                    "accruals_ratio":     _div(
                        (net_inc - cfo) if net_inc is not None and cfo is not None else None,
                        avg_assets,
                    ),
                    "interest_coverage":  int_cov,
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def get_value(self) -> pd.DataFrame:
        rows = []
        today = date_cls.today()
        for sym in self.symbols:
            km      = self._key_metrics_ttm(sym)
            profile = self._profile(sym)
            bal_list = self._balance(sym, limit=1)
            cf_list  = self._cashflow(sym, limit=1)
            est      = self._analyst_estimates(sym, limit=1)

            mkt     = _f(km, "marketCap")
            price   = _f(profile, "price")
            bc      = bal_list[0] if bal_list else None
            cc      = cf_list[0]  if cf_list  else None

            tot_eq      = _f(bc, "totalStockholdersEquity")
            intangibles = _f(bc, "goodwillAndIntangibleAssets", "goodwill")
            fcf         = _f(cc, "freeCashFlow")
            buyback     = _f(cc, "commonStockRepurchased")
            div_paid    = _f(cc, "commonDividendsPaid")

            earnings_yield = _f(km, "earningsYieldTTM")
            pe             = _div(1, earnings_yield)
            fwd_eps        = _f(est[0], "epsAvg") if est else None
            fwd_pe         = _div(price, fwd_eps)

            tangible_eq    = (tot_eq - intangibles) if tot_eq is not None and intangibles is not None else tot_eq
            div_yield      = _div(-div_paid if div_paid is not None else None, mkt)
            buyback_yield  = _div(-buyback if buyback is not None else None, mkt)
            shareholder_yield = (
                (div_yield or 0) + (buyback_yield or 0)
                if div_yield is not None or buyback_yield is not None
                else None
            )

            rows.append({
                "symbol":           sym,
                "date":             today,
                "pe_ratio":         pe,
                "forward_pe":       fwd_pe,
                "peg_ratio":        None,  # requires normalised LT growth rate — computed in signal model
                "earnings_yield":   earnings_yield,
                "pb_ratio":         _div(mkt, tot_eq),
                "p_tangible_book":  _div(mkt, tangible_eq),
                "ev_ebitda":        _f(km, "evToEBITDATTM"),
                "ev_sales":         _f(km, "evToSalesTTM"),
                "ev_fcf":           _f(km, "evToFreeCashFlowTTM"),
                "price_to_fcf":     _div(mkt, fcf),
                "fcf_yield":        _f(km, "freeCashFlowYieldTTM"),
                "dividend_yield":   div_yield,
                "buyback_yield":    buyback_yield,
                "shareholder_yield": shareholder_yield,
            })

        return pd.DataFrame(rows)

    def get_growth(self) -> pd.DataFrame:
        rows = []
        for sym in self.symbols:
            ann_list = self._financial_growth(sym, period="annual",  limit=10)
            qtr_list = self._financial_growth(sym, period="quarter", limit=10)

            for g in ann_list:
                rows.append({
                    "symbol":              sym,
                    "date":               g.get("date", "")[:10],
                    "revenue_growth_yoy": _f(g, "revenueGrowth"),
                    "eps_growth_yoy":     _f(g, "epsdilutedGrowth"),
                    "revenue_growth_qoq": None,
                    "eps_growth_qoq":     None,
                })

            for g in qtr_list:
                rows.append({
                    "symbol":              sym,
                    "date":               g.get("date", "")[:10],
                    "revenue_growth_yoy": None,
                    "eps_growth_yoy":     None,
                    "revenue_growth_qoq": _f(g, "revenueGrowth"),
                    "eps_growth_qoq":     _f(g, "epsdilutedGrowth"),
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df


if __name__ == "__main__":
    symbols = ["AAPL", "MSFT", "NVDA"]
    fd = FundamentalsData(symbols)

    print("=== QUALITY ===")
    print(fd.get_quality().to_string())
    print("\n=== VALUE ===")
    print(fd.get_value().to_string())
    print("\n=== GROWTH ===")
    print(fd.get_growth().to_string())
