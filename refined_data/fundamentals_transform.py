import pandas as pd
from datetime import date as date_cls
from data_collection.fundamentals_data import FundamentalsData


def _div(num, den) -> float | None:
    try:
        if num is None or den is None or float(den) == 0:
            return None
        return float(num) / float(den)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _f(d: dict | None, *keys: str) -> float | None:
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
    "pe_ratio", "forward_pe", "earnings_yield",
    "pb_ratio", "p_tangible_book", "price_to_sales",
    "ev_ebitda", "ev_sales", "ev_fcf",
    "price_to_fcf", "fcf_yield",
    "dividend_yield", "buyback_yield", "shareholder_yield",
]

GROWTH_COLS = [
    "symbol", "date", "period",
    "revenue_growth_yoy", "eps_growth_yoy",
    "revenue_growth_qoq", "eps_growth_qoq",
]


def build_quality(fd: FundamentalsData) -> pd.DataFrame:
    rows = []
    for sym in fd.symbols:
        inc_df = fd.income(sym)
        bal_df = fd.balance(sym)
        cf_df  = fd.cashflow(sym)
        km_df  = fd.key_metrics(sym)
        rat_df = fd.ratios(sym)

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

            # previous year's balance sheet — needed for accruals ratio denominator (avg assets)
            earlier    = [d for d in bal_dates if d < date_str]
            bp         = bal_by_date[earlier[-1]] if earlier else {}

            net_inc     = _f(ic, "netIncome")
            int_exp     = _f(ic, "interestExpense")
            ebit        = _f(ic, "ebit", "operatingIncome")
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
                "operating_margin":  _f(rat, "operatingProfitMargin", "ebitMargin"),
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
                # None when company earns net interest income (no interest expense)
                "interest_coverage": _div(ebit, abs(int_exp)) if int_exp else None,
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def build_value(fd: FundamentalsData) -> pd.DataFrame:
    rows = []
    today = date_cls.today()

    for sym in fd.symbols:
        km_ttm  = fd.key_metrics_ttm(sym)
        prof_df = fd.profile(sym)
        bal_df  = fd.balance(sym, limit=1)
        cf_df   = fd.cashflow(sym, limit=1)
        inc_df  = fd.income(sym, limit=1)
        est_df  = fd.analyst_estimates(sym, limit=1)

        km   = km_ttm.iloc[0].to_dict()  if not km_ttm.empty  else {}
        prof = prof_df.iloc[0].to_dict() if not prof_df.empty else {}
        bc   = bal_df.iloc[0].to_dict()  if not bal_df.empty  else {}
        cc   = cf_df.iloc[0].to_dict()   if not cf_df.empty   else {}
        ic   = inc_df.iloc[0].to_dict()  if not inc_df.empty  else {}
        est  = est_df.iloc[0].to_dict()  if not est_df.empty  else {}

        mkt         = _f(km,   "marketCapTTM", "marketCap")
        price       = _f(prof, "price")
        revenue     = _f(ic,   "revenue")
        tot_eq      = _f(bc,   "totalStockholdersEquity")
        intangibles = _f(bc,   "goodwillAndIntangibleAssets", "goodwill")
        fcf         = _f(cc,   "freeCashFlow")
        buyback     = _f(cc,   "commonStockRepurchased")
        div_paid    = _f(cc,   "commonDividendsPaid", "dividendsPaid")

        earnings_yield = _f(km, "earningsYieldTTM")
        fwd_eps        = _f(est, "estimatedEpsAvg", "epsAvg")
        tangible_eq    = (tot_eq - intangibles) if tot_eq is not None and intangibles is not None else tot_eq
        div_yield      = _div(-div_paid  if div_paid  is not None else None, mkt)
        buyback_yield  = _div(-buyback   if buyback   is not None else None, mkt)
        shareholder_yield = (
            (div_yield or 0) + (buyback_yield or 0)
            if div_yield is not None or buyback_yield is not None
            else None
        )

        rows.append({
            "symbol":            sym,
            "date":              today,
            "pe_ratio":          _div(1, earnings_yield),
            "forward_pe":        _div(price, fwd_eps),
            "earnings_yield":    earnings_yield,
            "pb_ratio":          _div(mkt, tot_eq),
            "p_tangible_book":   _div(mkt, tangible_eq),
            "price_to_sales":    _div(mkt, revenue),
            "ev_ebitda":         _f(km, "evToEBITDATTM", "enterpriseValueOverEBITDATTM"),
            "ev_sales":          _f(km, "evToSalesTTM"),
            "ev_fcf":            _f(km, "evToFreeCashFlowTTM"),
            "price_to_fcf":      _div(mkt, fcf),
            "fcf_yield":         _f(km, "freeCashFlowYieldTTM"),
            "dividend_yield":    div_yield,
            "buyback_yield":     buyback_yield,
            "shareholder_yield": shareholder_yield,
        })

    return pd.DataFrame(rows)


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
