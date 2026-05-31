"""
FundamentalsData — pulls financial statement data from Financial Modeling Prep (FMP).
Note on eps_revision_3m: requires storing analyst estimate snapshots over time and
comparing today's consensus to 90 days ago. No single API pull can reconstruct
that history — the field is set to None and must be populated by a scheduled
snapshot job.
"""
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

    def _income(self, sym: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._fetch("income-statement", symbol=sym, period=period, limit=limit)

    def _balance(self, sym: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._fetch("balance-sheet-statement", symbol=sym, period=period, limit=limit)

    def _cashflow(self, sym: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._fetch("cash-flow-statement", symbol=sym, period=period, limit=limit)

    def _key_metrics_ttm(self, sym: str) -> dict:
        data = self._fetch("key-metrics-ttm", symbol=sym)
        return data[0] if data else {}

    def _profile(self, sym: str) -> dict:
        data = self._fetch("profile", symbol=sym)
        return data[0] if data else {}

    def _analyst_estimates(self, sym: str, limit: int = 2) -> list[dict]:
        return self._fetch("analyst-estimates", symbol=sym, period="annual", limit=limit)

    # --- Public getters — each returns a DataFrame ready for DB insertion ---

    def get_quality(self) -> pd.DataFrame:
        """
        One row per (symbol, fiscal_year_end_date), ~4–5 years of history.
        All metrics computed from raw statements for calculation consistency.
        """
        rows = []
        for sym in self.symbols:
            inc_list = self._income(sym)
            bal_list = self._balance(sym)
            cf_list  = self._cashflow(sym)

            if not inc_list:
                continue

            for i, ic in enumerate(inc_list):
                bc = bal_list[i]     if i     < len(bal_list) else None
                cc = cf_list[i]      if i     < len(cf_list)  else None
                bp = bal_list[i + 1] if i + 1 < len(bal_list) else None

                revenue    = _f(ic, "revenue")
                gross_p    = _f(ic, "grossProfit")
                ebit       = _f(ic, "ebit", "operatingIncome")
                ebitda     = _f(ic, "ebitda")
                net_inc    = _f(ic, "netIncome")
                int_exp    = _f(ic, "interestExpense")
                tax        = _f(ic, "incomeTaxExpense")
                pretax     = _f(ic, "incomeBeforeTax")

                cfo        = _f(cc, "operatingCashFlow")
                fcf        = _f(cc, "freeCashFlow")

                tot_eq     = _f(bc, "totalStockholdersEquity")
                tot_assets = _f(bc, "totalAssets")
                ltd        = _f(bc, "longTermDebt")
                cash_b     = _f(bc, "cashAndCashEquivalents", "cashAndShortTermInvestments")
                cur_assets = _f(bc, "totalCurrentAssets")
                cur_liab   = _f(bc, "totalCurrentLiabilities")

                a1         = _f(bp, "totalAssets") if bp else None
                avg_assets = _div((tot_assets or 0) + (a1 or 0), 2) if tot_assets and a1 else None

                tax_rt  = _div(tax, pretax) or 0.21
                nopat   = ebit * (1 - tax_rt) if ebit is not None else None
                inv_cap = ((tot_eq or 0) + (ltd or 0) - (cash_b or 0)) or None
                net_debt = ((ltd or 0) - (cash_b or 0)) if ltd is not None else None

                rows.append({
                    "symbol":             sym,
                    "date":               ic.get("date", "")[:10],
                    "roe":                _div(net_inc, tot_eq),
                    "roa":                _div(net_inc, tot_assets),
                    "roic":               _div(nopat, inv_cap),
                    "gross_margin":       _div(gross_p, revenue),
                    "operating_margin":   _div(ebit, revenue),
                    "net_margin":         _div(net_inc, revenue),
                    "fcf_margin":         _div(fcf, revenue),
                    "cash_conversion":    _div(fcf, net_inc),
                    "accruals_ratio":     _div(
                        (net_inc - cfo) if net_inc is not None and cfo is not None else None,
                        avg_assets,
                    ),
                    "debt_to_equity":     _div(ltd, tot_eq),
                    "net_debt_to_ebitda": _div(net_debt, ebitda),
                    "interest_coverage":  _div(ebit, abs(int_exp) if int_exp is not None else None),
                    "current_ratio":      _div(cur_assets, cur_liab),
                    "asset_turnover":     _div(revenue, tot_assets),
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def get_value(self) -> pd.DataFrame:
        """
        One row per symbol at today's date.
        Uses key-metrics-ttm for trailing ratios; profile for price and market cap;
        analyst-estimates for forward EPS (forward PE).
        PE is derived as 1 / earningsYieldTTM (FMP stable API does not expose peRatio
        directly in key-metrics-ttm). PB and P/TangibleBook are computed from market
        cap and the most recent annual balance sheet.
        """
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
        """
        Two row types in the same table:
          - Annual  (fiscal_year_end_date): revenue_growth_yoy, eps_growth_yoy
          - Quarterly (quarter_end_date):   revenue_growth_qoq, eps_growth_qoq
        Inapplicable columns per row type are None (stored as NULL).
        revenue_vs_sector_growth: cross-universe, computed in signal model.
        eps_revision_3m: requires stored estimate snapshots — always None here.
        """
        rows = []
        for sym in self.symbols:
            inc_list = self._income(sym, limit=5)
            q_list   = self._income(sym, period="quarter", limit=8)

            # Annual YoY
            if len(inc_list) >= 2:
                for i in range(len(inc_list) - 1):
                    ic_now  = inc_list[i]
                    ic_prev = inc_list[i + 1]

                    rev_now  = _f(ic_now,  "revenue")
                    rev_prev = _f(ic_prev, "revenue")
                    eps_now  = _f(ic_now,  "epsDiluted", "eps")
                    eps_prev = _f(ic_prev, "epsDiluted", "eps")

                    rows.append({
                        "symbol":                   sym,
                        "date":                     ic_now.get("date", "")[:10],
                        "revenue_growth_yoy":       _div(rev_now - rev_prev, abs(rev_prev)) if rev_now and rev_prev else None,
                        "eps_growth_yoy":           _div(eps_now - eps_prev, abs(eps_prev)) if eps_now and eps_prev else None,
                        "revenue_growth_qoq":       None,
                        "eps_growth_qoq":           None,
                    })

            # Quarterly QoQ
            if len(q_list) >= 2:
                for i in range(len(q_list) - 1):
                    q0 = q_list[i]
                    q1 = q_list[i + 1]

                    rev_now  = _f(q0, "revenue")
                    rev_prev = _f(q1, "revenue")
                    eps_now  = _f(q0, "epsDiluted", "eps")
                    eps_prev = _f(q1, "epsDiluted", "eps")

                    rows.append({
                        "symbol":                   sym,
                        "date":                     q0.get("date", "")[:10],
                        "revenue_growth_yoy":       None,
                        "eps_growth_yoy":           None,
                        "revenue_growth_qoq":       _div(rev_now - rev_prev, abs(rev_prev)) if rev_now and rev_prev else None,
                        "eps_growth_qoq":           _div(eps_now - eps_prev, abs(eps_prev)) if eps_now and eps_prev else None,
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
