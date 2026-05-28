import yfinance as yf
import pandas as pd
import time


_ALL_COLUMNS = [
    "symbol", "date",
    "roe", "roic", "gross_margin", "operating_margin", "fcf_margin",
    "cash_conversion", "accruals_ratio", "debt_to_equity", "interest_coverage",
    "pe_ratio", "forward_pe", "peg_ratio", "pb_ratio", "ev_ebitda",
    "price_to_fcf", "fcf_yield", "earnings_yield", "dividend_yield", "buyback_yield",
    "revenue_ttm", "revenue_growth_yoy", "revenue_growth_qoq",
    "eps_ttm", "eps_growth_yoy", "eps_growth_qoq",
    "revenue_vs_sector_growth", "eps_revision_3m", "growth_consistency_score",
]


def _row(df: pd.DataFrame, *names: str) -> float | None:
    """Return most-recent value from a statement DataFrame, trying multiple row name variants."""
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            series = df.loc[name].dropna()
            if not series.empty:
                return float(series.iloc[0])
    return None


def _div(num, den) -> float | None:
    try:
        if num is None or den is None or float(den) == 0:
            return None
        return float(num) / float(den)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class FundamentalsData:
    """
    Fetches quality, value, and growth fundamentals from yfinance.

    Layer 1 — ticker.info: most fields, one call per symbol.
    Layer 2 — financial statements: ROIC, accruals, interest coverage,
               buyback yield, QoQ growth, growth consistency.

    Limitation: yfinance provides current TTM/MRQ data only —
    no point-in-time history. Date is tagged as today.
    """

    def get_fundamentals(
        self,
        symbols: list[str],
        sector_mapping: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """
        Returns a DataFrame with one row per symbol, columns matching
        the fundamentals_repository schema.

        sector_mapping: DataFrame with columns [symbol, sector].
        If provided, revenue_vs_sector_growth is computed here.
        If None, that column is left as None.
        """
        records = [self._fetch_one(s) for s in symbols]
        df = pd.DataFrame(records, columns=_ALL_COLUMNS)

        if sector_mapping is not None and not df.empty:
            df = self._add_sector_relative_growth(df, sector_mapping)

        return df

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_one(self, symbol: str) -> dict:
        record = {col: None for col in _ALL_COLUMNS}
        record["symbol"] = symbol
        record["date"] = pd.Timestamp.today().normalize()
        record["eps_revision_3m"] = None   # no free source — requires paid provider

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            # ---- Layer 1: direct from ticker.info ----
            roe             = info.get("returnOnEquity")
            gross_margin    = info.get("grossMargins")
            op_margin       = info.get("operatingMargins")
            d_to_e_raw      = info.get("debtToEquity")    # yfinance: % not ratio (150 = 1.5x)
            pe              = info.get("trailingPE")
            forward_pe      = info.get("forwardPE")
            peg             = info.get("pegRatio")
            pb              = info.get("priceToBook")
            ev_ebitda       = info.get("enterpriseToEbitda")
            div_yield       = info.get("dividendYield")
            rev_growth_yoy  = info.get("revenueGrowth")
            eps_growth_yoy  = info.get("earningsGrowth")
            fcf             = info.get("freeCashflow")
            op_cf           = info.get("operatingCashflow")
            revenue_ttm     = info.get("totalRevenue")
            net_income      = info.get("netIncomeToCommon")
            market_cap      = info.get("marketCap")
            eps_ttm         = info.get("trailingEps")

            record["roe"]               = roe
            record["gross_margin"]      = gross_margin
            record["operating_margin"]  = op_margin
            record["debt_to_equity"]    = _div(d_to_e_raw, 100)
            record["pe_ratio"]          = pe
            record["forward_pe"]        = forward_pe
            record["peg_ratio"]         = peg
            record["pb_ratio"]          = pb
            record["ev_ebitda"]         = ev_ebitda
            record["dividend_yield"]    = div_yield
            record["revenue_growth_yoy"] = rev_growth_yoy
            record["eps_growth_yoy"]    = eps_growth_yoy
            record["revenue_ttm"]       = revenue_ttm
            record["eps_ttm"]           = eps_ttm

            # Computed from info fields
            record["earnings_yield"]    = _div(1, pe)
            record["fcf_margin"]        = _div(fcf, revenue_ttm)
            record["fcf_yield"]         = _div(fcf, market_cap)
            record["price_to_fcf"]      = _div(market_cap, fcf)
            record["cash_conversion"]   = _div(fcf, net_income)

            # ---- Layer 2: financial statements ----
            try:
                fin  = ticker.financials
                bs   = ticker.balance_sheet
                cf   = ticker.cashflow
                qfin = ticker.quarterly_financials

                # ROIC = NOPAT / Invested Capital
                ebit           = _row(fin, "EBIT", "Operating Income")
                tax_expense    = _row(fin, "Tax Provision", "Income Tax Expense")
                pretax_income  = _row(fin, "Pretax Income")
                total_debt     = _row(bs,  "Total Debt", "Long Term Debt")
                equity         = _row(bs,  "Stockholders Equity", "Common Stock Equity",
                                          "Total Equity Gross Minority Interest")
                cash_equiv     = _row(bs,  "Cash And Cash Equivalents",
                                          "Cash Cash Equivalents And Short Term Investments")
                total_assets   = _row(bs,  "Total Assets")

                if ebit is not None and equity is not None:
                    tax_rate = _div(tax_expense, pretax_income) or 0.21
                    tax_rate = max(0.0, min(tax_rate, 0.40))   # clamp: anomalies happen
                    nopat = ebit * (1 - tax_rate)
                    invested_capital = (total_debt or 0) + equity - (cash_equiv or 0)
                    record["roic"] = _div(nopat, invested_capital)

                # Accruals ratio = (Net Income - Operating CF) / Total Assets
                if net_income is not None and op_cf is not None and total_assets:
                    record["accruals_ratio"] = (net_income - op_cf) / total_assets

                # Interest coverage = EBIT / |Interest Expense|
                int_exp = _row(fin, "Interest Expense", "Interest Expense Non Operating")
                if ebit is not None and int_exp is not None and int_exp != 0:
                    record["interest_coverage"] = _div(ebit, abs(int_exp))

                # Buyback yield = |Repurchases| / Market Cap
                repurchase = _row(cf, "Repurchase Of Capital Stock",
                                      "Common Stock Repurchased",
                                      "Purchase Of Business")
                if repurchase is not None and market_cap:
                    record["buyback_yield"] = _div(abs(repurchase), market_cap)

                # Revenue growth QoQ (most recent quarter vs prior quarter)
                if qfin is not None and not qfin.empty:
                    rev_q = None
                    for name in ("Total Revenue", "Operating Revenue"):
                        if name in qfin.index:
                            rev_q = qfin.loc[name].dropna()
                            break
                    if rev_q is not None and len(rev_q) >= 2:
                        record["revenue_growth_qoq"] = _div(
                            float(rev_q.iloc[0]) - float(rev_q.iloc[1]),
                            abs(float(rev_q.iloc[1])),
                        )

                    # EPS / Net Income growth QoQ
                    ni_q = None
                    for name in ("Net Income", "Net Income Common Stockholders",
                                 "Net Income Including Noncontrolling Interests"):
                        if name in qfin.index:
                            ni_q = qfin.loc[name].dropna()
                            break
                    if ni_q is not None and len(ni_q) >= 2 and float(ni_q.iloc[1]) != 0:
                        record["eps_growth_qoq"] = _div(
                            float(ni_q.iloc[0]) - float(ni_q.iloc[1]),
                            abs(float(ni_q.iloc[1])),
                        )

                # Growth consistency: fraction of annual periods with positive revenue growth
                if fin is not None and not fin.empty:
                    rev_a = None
                    for name in ("Total Revenue", "Operating Revenue"):
                        if name in fin.index:
                            rev_a = fin.loc[name].dropna()
                            break
                    if rev_a is not None and len(rev_a) >= 2:
                        n = min(len(rev_a) - 1, 4)
                        positive = sum(
                            float(rev_a.iloc[i]) > float(rev_a.iloc[i + 1])
                            for i in range(n)
                        )
                        record["growth_consistency_score"] = positive / n

            except Exception as e_stmt:
                print(f"  [{symbol}] statement layer failed: {e_stmt}")

        except Exception as e:
            print(f"[{symbol}] fetch failed: {e}")

        time.sleep(0.15)   # stay within yfinance rate limits for large universes
        return record

    def _add_sector_relative_growth(
        self,
        df: pd.DataFrame,
        sector_mapping: pd.DataFrame,
    ) -> pd.DataFrame:
        df = df.copy()
        sec = sector_mapping.set_index("symbol")["sector"]
        df["_sector"] = df["symbol"].map(sec)

        sector_avg = df.groupby("_sector")["revenue_growth_yoy"].transform("mean")
        df["revenue_vs_sector_growth"] = df["revenue_growth_yoy"] - sector_avg
        df = df.drop(columns=["_sector"])
        return df


if __name__ == "__main__":
    import database.fundamentals_repository as fundamentals_repo
    import database.sector_data_repository as sector_repo

    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]

    sector_df = sector_repo.get_sector_mapping(symbols)
    fd = FundamentalsData()
    df = fd.get_fundamentals(symbols, sector_mapping=sector_df)

    print(df.T)

    fundamentals_repo.create_fundamentals_table()
    fundamentals_repo.insert_fundamentals(df)
    print("Inserted successfully.")
