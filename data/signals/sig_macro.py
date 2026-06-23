import pandas as pd
import numpy as np
from dataclasses import dataclass, fields

import database.market.macro_repo as macro_repo


def _python_scalar(v):
    if isinstance(v, np.generic):
        return v.item()
    return v


@dataclass
class MacroSnapshot:
    signal_day: pd.Timestamp

    # Yield curve
    yield_2y: float
    yield_10y: float
    yield_curve_2_10: float  # 10y - 2y
    yield_curve_3m_10: float  # 10y - 3m

    # Real yields (TIPS)
    real_yield_10y: float

    # Breakeven inflation (market expectations)
    breakeven_10y: float

    # Policy
    fed_funds_rate: float

    # Credit spreads (percent, e.g. 3.5 = 350 bps)
    spread_hy: float
    spread_ig: float
    ted_spread: float

    # Inflation
    cpi_yoy: float
    cpi_core_yoy: float

    # Labor
    unemployment_rate: float
    jobless_claims: float

    # Risk sentiment
    vix: float

    # Dollar & commodities
    dxy: float
    oil_wti: float

    def __post_init__(self) -> None:
        for f in fields(self):
            setattr(self, f.name, _python_scalar(getattr(self, f.name)))

    def rate_environment(self) -> dict[str, bool]:
        return {
            "curve_normal": self.yield_curve_2_10 > 0,
            "curve_steep": self.yield_curve_2_10 > 1.0,
            "curve_inverted": self.yield_curve_2_10 < 0,
            "real_rates_high": self.real_yield_10y > 2.0,
            "real_rates_neg": self.real_yield_10y < 0,
            "rates_low": self.yield_10y < 3.0,
            "rates_high": self.yield_10y > 5.0,
        }

    def credit_conditions(self) -> dict[str, bool]:
        return {
            "credit_risk_on": self.spread_hy < 4.0,  # <400 bps
            "credit_stress": self.spread_hy > 6.0,  # >600 bps
            "ig_tight": self.spread_ig < 1.0,  # <100 bps
            "liquidity_ok": self.ted_spread < 0.5,  # <50 bps
            "liquidity_stress": self.ted_spread > 1.0,
        }

    def inflation_regime(self) -> dict[str, bool]:
        return {
            "inflation_target": 1.5 < self.cpi_yoy < 3.0,
            "inflation_elevated": self.cpi_yoy > 3.0,
            "inflation_high": self.cpi_yoy > 5.0,
            "inflation_low": self.cpi_yoy < 1.5,
            "expectations_anchored": self.breakeven_10y < 2.5,
            "expectations_high": self.breakeven_10y > 3.0,
        }

    def risk_sentiment(self) -> dict[str, bool]:
        return {
            "low_vol": self.vix < 15,
            "normal_vol": 15 <= self.vix < 25,
            "elevated_fear": self.vix >= 25,
            "high_fear": self.vix >= 30,
            "extreme_fear": self.vix >= 40,
        }

    def labor_market(self) -> dict[str, bool]:
        return {
            "full_employment": self.unemployment_rate < 4.5,
            "labor_weakening": self.unemployment_rate > 5.5,
            "claims_elevated": self.jobless_claims > 250_000,
            "claims_high": self.jobless_claims > 350_000,
        }

    def macro_score(self) -> float:
        """0-1: higher = more favorable macro backdrop for equities."""
        score = 0.5
        score += 0.10 if self.yield_curve_2_10 > 0 else -0.10
        score += (
            0.10 if self.spread_hy < 4.0 else (-0.10 if self.spread_hy > 6.0 else 0.0)
        )
        score += 0.10 if self.vix < 20 else (-0.20 if self.vix >= 30 else -0.05)
        score += 0.05 if 1.5 < self.cpi_yoy < 3.5 else -0.05
        score -= 0.05 if self.real_yield_10y > 2.0 else 0.0
        score += 0.05 if self.unemployment_rate < 4.5 else -0.05
        return max(0.0, min(1.0, score))


class MacroModel:
    def __init__(self, signal_day: pd.Timestamp):
        self.signal_day = signal_day
        self._row: pd.Series | None = None
        self._load_data()

    def _load_data(self) -> None:
        df = macro_repo.get(end_date=str(self.signal_day.date()))
        if df.empty:
            raise ValueError(f"No macro data as of {self.signal_day.date()}")
        self._row = df.iloc[-1]

    def build_snapshot(self) -> MacroSnapshot:
        r = self._row
        return MacroSnapshot(
            signal_day=self.signal_day,
            yield_2y=r["yield_2y"],
            yield_10y=r["yield_10y"],
            yield_curve_2_10=r["yield_curve_2_10"],
            yield_curve_3m_10=r["yield_curve_3m_10"],
            real_yield_10y=r["real_yield_10y"],
            breakeven_10y=r["breakeven_10y"],
            fed_funds_rate=r["fed_funds_rate"],
            spread_hy=r["spread_hy"],
            spread_ig=r["spread_ig"],
            ted_spread=r["ted_spread"],
            cpi_yoy=r["cpi_yoy"],
            cpi_core_yoy=r["cpi_core_yoy"],
            unemployment_rate=r["unemployment_rate"],
            jobless_claims=r["jobless_claims"],
            vix=r["vix"],
            dxy=r["dxy"],
            oil_wti=r["oil_wti"],
        )


def print_snapshot_report(snap: MacroSnapshot) -> None:
    print(f"\n=== Macro | {snap.signal_day.date()} ===")
    print(
        f"  Yield curve 2-10: {snap.yield_curve_2_10:+.2f}  |  10y: {snap.yield_10y:.2f}%  |  FFR: {snap.fed_funds_rate:.2f}%"
    )
    print(
        f"  Real yield 10y: {snap.real_yield_10y:.2f}%  |  Breakeven 10y: {snap.breakeven_10y:.2f}%"
    )
    print(
        f"  HY spread: {snap.spread_hy:.2f}%  |  IG spread: {snap.spread_ig:.2f}%  |  TED: {snap.ted_spread:.2f}%"
    )
    print(f"  CPI YoY: {snap.cpi_yoy:.2f}%  |  Core CPI YoY: {snap.cpi_core_yoy:.2f}%")
    print(
        f"  Unemployment: {snap.unemployment_rate:.1f}%  |  Jobless claims: {snap.jobless_claims:,.0f}"
    )
    print(f"  VIX: {snap.vix:.1f}  |  DXY: {snap.dxy:.1f}  |  WTI: ${snap.oil_wti:.1f}")
    print(f"  Macro Score: {snap.macro_score():.3f}")
    print(f"  Rate Env:    {snap.rate_environment()}")
    print(f"  Credit:      {snap.credit_conditions()}")
    print(f"  Inflation:   {snap.inflation_regime()}")
    print(f"  Risk:        {snap.risk_sentiment()}")
    print(f"  Labor:       {snap.labor_market()}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2024-06-30")
    model = MacroModel(signal_day=signal_day)
    print_snapshot_report(model.build_snapshot())
