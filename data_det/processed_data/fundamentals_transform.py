import pandas as pd
from data_det.raw_data.fundamentals_data import FundamentalsData


def _div(num, den) -> float | None:
    try:
        if num is None or den is None or float(den) == 0:
            return None
        return float(num) / float(den)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _f(d: dict | None, key: str) -> float | None:
    if not d:
        return None
    v = d.get(key)
    if v is not None:
        try:
            f = float(v)
            if f == f:  # reject NaN
                return f
        except (TypeError, ValueError):
            pass
    return None


QUALITY_COLS = [
    "symbol", "date",
    "roe", "roa", "roic",
    "gross_margin", "operating_margin", "net_margin", "fcf_margin",
    "cash_conversion", "accruals_ratio",
    "debt_to_equity", "net_debt_to_ebitda", "interest_coverage",
    "current_ratio", "asset_turnover",
]

VALUE_COLS = [
    "symbol", "date",
    "pe_ratio", "earnings_yield",
    "pb_ratio", "price_to_sales",
    "ev_ebitda", "ev_sales", "ev_fcf",
    "price_to_fcf", "fcf_yield",
    "dividend_yield",
]

GROWTH_COLS = [
    "symbol", "date", "period",
    "revenue_growth_yoy", "eps_growth_yoy",
    "revenue_growth_qoq", "eps_growth_qoq",
]


def build_quality(fd: FundamentalsData) -> pd.DataFrame:
    rows = []
    for sym in fd.symbols:
        for period in ("annual", "quarter"):
            inc_df = fd.income(sym, period=period)
            bal_df = fd.balance(sym, period=period)
            cf_df  = fd.cashflow(sym, period=period)
            km_df  = fd.key_metrics(sym, period=period)
            rat_df = fd.ratios(sym, period=period)

            if inc_df.empty:
                continue

            bal_by_date = {r["date"][:10]: r for r in bal_df.to_dict("records")} if not bal_df.empty else {}
            cf_by_date  = {r["date"][:10]: r for r in cf_df.to_dict("records")}  if not cf_df.empty else {}
            km_by_date  = {r["date"][:10]: r for r in km_df.to_dict("records")}  if not km_df.empty else {}
            rat_by_date = {r["date"][:10]: r for r in rat_df.to_dict("records")} if not rat_df.empty else {}
            bal_dates   = sorted(bal_by_date)

            for ic in inc_df.to_dict("records"):
                date_str = str(ic.get("date", ""))[:10]
                bc  = bal_by_date.get(date_str, {})
                cc  = cf_by_date.get(date_str, {})
                km  = km_by_date.get(date_str, {})
                rat = rat_by_date.get(date_str, {})

                # previous period's balance sheet — needed for accruals ratio denominator (avg assets)
                earlier    = [d for d in bal_dates if d < date_str]
                bp         = bal_by_date[earlier[-1]] if earlier else {}

                net_inc     = _f(ic, "netIncome")
                int_exp     = _f(ic, "interestExpense")
                ebit        = _f(ic, "operatingIncome")
                revenue     = _f(ic, "revenue")
                cfo         = _f(cc, "operatingCashFlow")
                fcf         = _f(cc, "freeCashFlow")
                tot_assets  = _f(bc, "totalAssets")
                prev_assets = _f(bp, "totalAssets")
                avg_assets  = _div((tot_assets or 0) + (prev_assets or 0), 2) if tot_assets and prev_assets else None

                rows.append({
                    "symbol":            sym,
                    "date":              date_str,
                    "roe":               _f(km,  "returnOnEquity"),
                    "roa":               _f(km,  "returnOnAssets"),
                    "roic":              _f(km,  "returnOnInvestedCapital"),
                    "gross_margin":      _f(rat, "grossProfitMargin"),
                    "operating_margin":  _f(rat, "operatingProfitMargin"),
                    "net_margin":        _f(rat, "netProfitMargin"),
                    "debt_to_equity":    _f(rat, "debtToEquityRatio"),
                    "asset_turnover":    _f(rat, "assetTurnover"),
                    "net_debt_to_ebitda": _f(km, "netDebtToEBITDA"),
                    "current_ratio":     _f(km,  "currentRatio"),
                    "fcf_margin":        _div(fcf, revenue),
                    "cash_conversion":   _div(fcf, net_inc),
                    "accruals_ratio":    _div(
                        (net_inc - cfo) if net_inc is not None and cfo is not None else None,
                        avg_assets,
                    ),
                    "interest_coverage": _div(ebit, abs(int_exp)) if int_exp else None,
                })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def build_value(fd: FundamentalsData) -> pd.DataFrame:
    rows = []
    for sym in fd.symbols:
        for period in ("annual", "quarter"):
            km_df  = fd.key_metrics(sym, period=period, limit=10)
            rat_df = fd.ratios(sym, period=period, limit=10)
            if km_df.empty:
                continue

            rat_by_date = {str(r["date"])[:10]: r for r in rat_df.to_dict("records")} if not rat_df.empty else {}

            for km in km_df.to_dict("records"):
                date_str = str(km.get("date", ""))[:10]
                if not date_str:
                    continue
                rat = rat_by_date.get(date_str, {})

                earnings_yield = _f(km, "earningsYield")
                fcf_yield      = _f(km, "freeCashFlowYield")

                rows.append({
                    "symbol":         sym,
                    "date":           date_str,
                    "pe_ratio":       _div(1, earnings_yield),
                    "earnings_yield": earnings_yield,
                    "pb_ratio":       _f(rat, "priceToBookRatio"),
                    "price_to_sales": _f(rat, "priceToSalesRatio"),
                    "ev_ebitda":      _f(km,  "evToEBITDA"),
                    "ev_sales":       _f(km,  "evToSales"),
                    "ev_fcf":         _f(km,  "evToFreeCashFlow"),
                    "price_to_fcf":   _div(1, fcf_yield),
                    "fcf_yield":      fcf_yield,
                    "dividend_yield": _f(rat, "dividendYield"),
                })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def build_growth(fd: FundamentalsData) -> pd.DataFrame:
    rows = []
    for sym in fd.symbols:
        for g in fd.financial_growth(sym, period="annual").to_dict("records"):
            rows.append({
                "symbol":             sym,
                "date":               str(g.get("date", ""))[:10],
                "period":             "annual",
                "revenue_growth_yoy": _f(g, "revenueGrowth"),
                "eps_growth_yoy":     _f(g, "epsdilutedGrowth"),
                "revenue_growth_qoq": None,
                "eps_growth_qoq":     None,
            })
        for g in fd.financial_growth(sym, period="quarter").to_dict("records"):
            rows.append({
                "symbol":             sym,
                "date":               str(g.get("date", ""))[:10],
                "period":             "quarter",
                "revenue_growth_yoy": None,
                "eps_growth_yoy":     None,
                "revenue_growth_qoq": _f(g, "revenueGrowth"),
                "eps_growth_qoq":     _f(g, "epsdilutedGrowth"),
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df
