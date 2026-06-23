import pandas as pd
from dataclasses import dataclass

import database.market.fundamentals_repo as fundamentals_repo


@dataclass
class FundamentalsSnapshot:
    ticker: str
    signal_day: pd.Timestamp
    datekey: pd.Timestamp
    calendardate: pd.Timestamp

    # Valuation (ART — trailing twelve months)
    pe: float
    pb: float
    ps: float
    evebitda: float
    divyield: float
    marketcap: float

    # Profitability (ART)
    roe: float
    roa: float
    roic: float
    grossmargin: float
    ebitdamargin: float
    netmargin: float
    fcf: float
    opinc: float

    # Earnings quality (ART)
    ncfo: float
    capex: float
    ebit: float
    intexp: float
    interest_coverage: float   # ebit / intexp
    capex_to_ocf: float        # abs(capex) / ncfo

    # Efficiency (ART)
    assetturnover: float
    rnd: float                 # absolute R&D spend
    rnd_intensity: float       # rnd / revenue

    # Balance sheet (ART)
    de: float
    currentratio: float
    cashneq: float
    workingcapital: float
    payoutratio: float

    # Reference levels (ART)
    revenue: float
    eps: float

    # Growth (YoY from ARQ: most recent quarter vs same quarter 1 year prior)
    revenue_growth_yoy: float
    eps_growth_yoy: float
    grossmargin_change_yoy: float
    opinc_growth_yoy: float

    # Cross-sectional percentiles
    roe_percentile: float
    revenue_growth_percentile: float
    evebitda_percentile: float
    fcf_percentile: float

    def valuation(self) -> dict[str, bool]:
        return {
            "pe_reasonable":       0 < self.pe < 30,
            "pb_reasonable":       0 < self.pb < 5,
            "ps_reasonable":       0 < self.ps < 5,
            "evebitda_reasonable": 0 < self.evebitda < 20,
            "pays_dividend":       self.divyield > 0,
            "large_cap":           self.marketcap >= 10_000_000_000,
            "mid_cap":             1_000_000_000 <= self.marketcap < 10_000_000_000,
        }

    def profitability(self) -> dict[str, bool]:
        return {
            "roe_positive":    self.roe > 0,
            "roe_strong":      self.roe > 0.15,
            "roa_positive":    self.roa > 0,
            "roic_positive":   self.roic > 0,
            "gross_margin_ok": self.grossmargin > 0.20,
            "net_margin_pos":  self.netmargin > 0,
            "fcf_positive":    self.fcf > 0,
            "opinc_positive":  self.opinc > 0,
        }

    def earnings_quality(self) -> dict[str, bool]:
        return {
            "interest_covered":    self.interest_coverage > 3.0,
            "strong_coverage":     self.interest_coverage > 10.0,
            "low_capex_intensity": self.capex_to_ocf < 0.5,
            "ocf_positive":        self.ncfo > 0,
        }

    def efficiency(self) -> dict[str, bool]:
        return {
            "asset_turnover_ok": self.assetturnover > 0.5,
            "investing_in_rnd":  self.rnd_intensity > 0.05,
            "high_rnd":          self.rnd_intensity > 0.15,
        }

    def balance_sheet_health(self) -> dict[str, bool]:
        return {
            "low_leverage":        self.de < 1.0,
            "current_ratio_ok":    self.currentratio > 1.5,
            "has_cash":            self.cashneq > 0,
            "positive_working_cap": self.workingcapital > 0,
            "sustainable_payout":  0 <= self.payoutratio < 0.75,
        }

    def growth_momentum(self) -> dict[str, bool]:
        return {
            "revenue_growing":  self.revenue_growth_yoy > 0,
            "revenue_strong":   self.revenue_growth_yoy > 0.10,
            "eps_growing":      self.eps_growth_yoy > 0,
            "eps_strong":       self.eps_growth_yoy > 0.10,
            "margin_expanding": self.grossmargin_change_yoy > 0,
            "opinc_growing":    self.opinc_growth_yoy > 0,
        }

    def quality_score(self) -> float:
        return (
            0.25 * self.roe_percentile +
            0.25 * self.revenue_growth_percentile +
            0.25 * self.fcf_percentile +
            0.15 * (100 - self.evebitda_percentile) +
            0.10 * min(max(self.netmargin * 100, 0), 100)
        ) / 100

    def risk_flags(self) -> dict[str, bool]:
        return {
            "high_leverage":      self.de > 2.0,
            "negative_fcf":       self.fcf < 0,
            "losing_money":       self.netmargin < 0,
            "revenue_declining":  self.revenue_growth_yoy < -0.05,
            "eps_declining":      self.eps_growth_yoy < -0.10,
            "interest_at_risk":   0 < self.interest_coverage < 1.5,
            "negative_ocf":       self.ncfo < 0,
        }


class FundamentalsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        tickers: list[str],
    ):
        self.signal_day = signal_day
        self.tickers = tickers
        self.data = None
        self._load_data()

    def _from_db(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        art = fundamentals_repo.get_latest(self.tickers, "ART", self.signal_day)
        lookback = self.signal_day - pd.Timedelta(days=730)
        arq = fundamentals_repo.get(
            tickers=self.tickers,
            dimension="ARQ",
            start_date=str(lookback.date()),
            end_date=str(self.signal_day.date()),
        )
        return art, arq

    def _compute_growth(self, arq: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for tkr, grp in arq.groupby("ticker"):
            grp = grp.sort_values("datekey")
            if len(grp) < 5:
                rows.append({
                    "ticker":                 tkr,
                    "revenue_growth_yoy":     float("nan"),
                    "eps_growth_yoy":         float("nan"),
                    "grossmargin_change_yoy": float("nan"),
                    "opinc_growth_yoy":       float("nan"),
                })
                continue
            latest = grp.iloc[-1]
            prior  = grp.iloc[-5]

            def safe_growth(now, then):
                if pd.isna(now) or pd.isna(then) or then == 0:
                    return float("nan")
                return (now - then) / abs(then)

            rows.append({
                "ticker":                 tkr,
                "revenue_growth_yoy":     safe_growth(latest["revenue"], prior["revenue"]),
                "eps_growth_yoy":         safe_growth(latest["eps"], prior["eps"]),
                "grossmargin_change_yoy": (
                    latest["grossmargin"] - prior["grossmargin"]
                    if pd.notna(latest["grossmargin"]) and pd.notna(prior["grossmargin"])
                    else float("nan")
                ),
                "opinc_growth_yoy": safe_growth(latest["opinc"], prior["opinc"]),
            })
        return pd.DataFrame(rows).set_index("ticker")

    def _compute_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        def safe_div(a, b, fallback=float("nan")):
            mask = pd.notna(a) & pd.notna(b) & (b != 0)
            result = pd.Series(fallback, index=a.index)
            result[mask] = a[mask] / b[mask]
            return result

        df["interest_coverage"] = safe_div(df["ebit"], df["intexp"])
        df["capex_to_ocf"]      = safe_div(df["capex"].abs(), df["ncfo"])
        df["rnd_intensity"]     = safe_div(df["rnd"], df["revenue"])
        return df

    def _load_data(self) -> None:
        art, arq = self._from_db()
        art = art.set_index("ticker")
        art = self._compute_derived(art)
        growth = self._compute_growth(arq)
        self.data = art.join(growth, how="left")
        self.data["roe_percentile"]            = self.data["roe"].rank(pct=True) * 100
        self.data["revenue_growth_percentile"] = self.data["revenue_growth_yoy"].rank(pct=True) * 100
        self.data["evebitda_percentile"]       = self.data["evebitda"].rank(pct=True) * 100
        self.data["fcf_percentile"]            = self.data["fcf"].rank(pct=True) * 100

    def get(self, ticker: str, col: str):
        if ticker not in self.data.index:
            raise ValueError(f"Ticker {ticker} not in data")
        if col not in self.data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.data.loc[ticker, col]

    def build_snapshot(self, ticker: str) -> FundamentalsSnapshot:
        g = lambda col: self.get(ticker, col)
        return FundamentalsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            datekey=pd.Timestamp(g("datekey")),
            calendardate=pd.Timestamp(g("calendardate")),
            pe=g("pe"),
            pb=g("pb"),
            ps=g("ps"),
            evebitda=g("evebitda"),
            divyield=g("divyield"),
            marketcap=g("marketcap"),
            roe=g("roe"),
            roa=g("roa"),
            roic=g("roic"),
            grossmargin=g("grossmargin"),
            ebitdamargin=g("ebitdamargin"),
            netmargin=g("netmargin"),
            fcf=g("fcf"),
            opinc=g("opinc"),
            ncfo=g("ncfo"),
            capex=g("capex"),
            ebit=g("ebit"),
            intexp=g("intexp"),
            interest_coverage=g("interest_coverage"),
            capex_to_ocf=g("capex_to_ocf"),
            assetturnover=g("assetturnover"),
            rnd=g("rnd"),
            rnd_intensity=g("rnd_intensity"),
            de=g("de"),
            currentratio=g("currentratio"),
            cashneq=g("cashneq"),
            workingcapital=g("workingcapital"),
            payoutratio=g("payoutratio"),
            revenue=g("revenue"),
            eps=g("eps"),
            revenue_growth_yoy=g("revenue_growth_yoy"),
            eps_growth_yoy=g("eps_growth_yoy"),
            grossmargin_change_yoy=g("grossmargin_change_yoy"),
            opinc_growth_yoy=g("opinc_growth_yoy"),
            roe_percentile=g("roe_percentile"),
            revenue_growth_percentile=g("revenue_growth_percentile"),
            evebitda_percentile=g("evebitda_percentile"),
            fcf_percentile=g("fcf_percentile"),
        )


if __name__ == "__main__":
    signal_day = pd.Timestamp("2024-06-30")
    tickers = ["AAPL", "MSFT", "GOOGL"]

    model = FundamentalsModel(signal_day=signal_day, tickers=tickers)

    for tkr in tickers:
        snap = model.build_snapshot(tkr)
        print(f"\n--- {tkr} ({snap.calendardate.date()}, filed {snap.datekey.date()}) ---")
        print(f"  valuation:       {snap.valuation()}")
        print(f"  profitability:   {snap.profitability()}")
        print(f"  earnings_quality:{snap.earnings_quality()}")
        print(f"  efficiency:      {snap.efficiency()}")
        print(f"  balance_sheet:   {snap.balance_sheet_health()}")
        print(f"  growth:          {snap.growth_momentum()}")
        print(f"  risk_flags:      {snap.risk_flags()}")
        print(f"  quality_score:   {snap.quality_score():.3f}")
