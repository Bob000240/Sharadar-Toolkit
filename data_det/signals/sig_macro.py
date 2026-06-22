import database.macro_repository as macro_repo
import database.indicator_repository as indicator_repo
import pandas as pd
from dataclasses import dataclass


def _classify_regime(
    vix: float,
    spy_above_sma_200: bool,
    yield_curve: float,
    credit_spread_hy: float,
) -> str:
    risk_off_signals = sum([
        vix > 25,
        not spy_above_sma_200,
        yield_curve < 0,
        credit_spread_hy > 5.0,
    ])
    if risk_off_signals == 0:
        return "risk_on"
    elif risk_off_signals >= 3:
        return "risk_off"
    else:
        return "caution"


@dataclass
class MacroSnapshot:
    # Identity
    signal_day: pd.Timestamp

    # Interest rates
    yield_10y: float
    yield_2y: float
    yield_curve: float      # 10y - 2y; positive = normal, negative = inverted
    real_yield: float       # 10y yield - CPI YoY

    # Economic indicators
    cpi_yoy: float
    unemployment_rate: float

    # Risk indicators
    credit_spread_hy: float     # high-yield spread (%)
    credit_spread_ig: float     # investment-grade spread (%)
    vix: float
    spy_above_sma_200: bool

    # Regime
    risk_regime: str    # "risk_on", "caution", "risk_off"

    @staticmethod
    def _pct(v: float) -> str:
        return f"{v:+.2f}%"

    def _fmt_header(self) -> str:
        regime_note = {
            "risk_on":  "All clear — low volatility, positive trend, tight spreads.",
            "caution":  "Mixed signals — monitor closely before new entries.",
            "risk_off": "Elevated risk — defensive posture recommended.",
        }.get(self.risk_regime, "")
        return "\n".join([
            f"MACRO SNAPSHOT | Signal date: {self.signal_day}",
            f"Risk regime: {self.risk_regime.upper()}  — {regime_note}",
        ])

    def _fmt_rates(self) -> str:
        curve_note = "normal (positive slope)" if self.yield_curve >= 0 else "INVERTED (recessionary signal)"
        return "\n".join([
            "--- INTEREST RATES ---",
            f"  10-year Treasury yield:   {self.yield_10y:.2f}%",
            f"   2-year Treasury yield:   {self.yield_2y:.2f}%",
            f"  Yield curve (10y - 2y):   {self.yield_curve:+.2f}%  ({curve_note})",
            f"  Real yield (10y - CPI):   {self.real_yield:+.2f}%  (positive = restrictive for growth)",
        ])

    def _fmt_economy(self) -> str:
        return "\n".join([
            "--- ECONOMIC CONDITIONS ---",
            f"  CPI (year-over-year):      {self.cpi_yoy:.1f}%  (Fed target: ~2%)",
            f"  Unemployment rate:         {self.unemployment_rate:.1f}%",
        ])

    def _fmt_risk_indicators(self) -> str:
        vix_note = "low" if self.vix < 20 else ("elevated" if self.vix < 30 else "HIGH — fear dominant")
        hy_note = "tight" if self.credit_spread_hy < 4 else ("widening" if self.credit_spread_hy < 6 else "WIDE — stress signal")
        return "\n".join([
            "--- RISK INDICATORS ---",
            f"  VIX (fear index):          {self.vix:.1f}  ({vix_note}; <20 = calm, >30 = fear)",
            f"  High-yield credit spread:  {self.credit_spread_hy:.2f}%  ({hy_note})",
            f"  Inv-grade credit spread:   {self.credit_spread_ig:.2f}%",
            f"  SPY above 200-day SMA:     {self.spy_above_sma_200}  (True = broad market uptrend intact)",
        ])

    def _fmt_regime_assessment(self) -> str:
        signals = {
            "Yield curve":      "positive" if self.yield_curve >= 0 else "negative",
            "VIX level":        "low" if self.vix < 20 else ("moderate" if self.vix < 30 else "high"),
            "Credit spreads":   "tight" if self.credit_spread_hy < 4 else "wide",
            "SPY trend":        "above SMA200" if self.spy_above_sma_200 else "below SMA200",
            "Real yield":       "negative (accommodative)" if self.real_yield < 0 else "positive (restrictive)",
        }
        lines = ["--- REGIME SIGNAL SUMMARY ---"]
        for label, state in signals.items():
            lines.append(f"  {label:<22}: {state}")
        return "\n".join(lines)

    def to_agent_prompt(self) -> str:
        return "\n\n".join([
            self._fmt_header(),
            self._fmt_rates(),
            self._fmt_economy(),
            self._fmt_risk_indicators(),
            self._fmt_regime_assessment(),
        ])


class MacroFactorsModel:
    def __init__(self, signal_day: pd.Timestamp):
        self.signal_day = signal_day
        self._macro = None
        self._spy_above_sma_200 = False
        self._load_data()

    def _load_data(self):
        macro_df = macro_repo.get_latest_macro(self.signal_day)
        spy_df = indicator_repo.get_latest_indicators(["SPY"], self.signal_day)

        if macro_df.empty:
            raise ValueError(f"No macro data found on or before {self.signal_day}")

        self._macro = macro_df.iloc[0]

        if not spy_df.empty:
            spy_row = spy_df[spy_df["symbol"] == "SPY"]
            if not spy_row.empty:
                r = spy_row.iloc[0]
                self._spy_above_sma_200 = bool(r["close"] > r["sma_200"]) if r["sma_200"] else False

    def build_snapshot(self) -> MacroSnapshot:
        m = self._macro
        return MacroSnapshot(
            signal_day=self.signal_day,
            yield_10y=m["yield_10y"],
            yield_2y=m["yield_2y"],
            yield_curve=m["yield_curve"],
            real_yield=m["real_yield"],
            cpi_yoy=m["cpi_yoy"],
            unemployment_rate=m["unemployment_rate"],
            credit_spread_hy=m["credit_spread_hy"],
            credit_spread_ig=m["credit_spread_ig"],
            vix=m["vix"],
            spy_above_sma_200=self._spy_above_sma_200,
            risk_regime=_classify_regime(
                m["vix"],
                self._spy_above_sma_200,
                m["yield_curve"],
                m["credit_spread_hy"],
            ),
        )


if __name__ == "__main__":
    signal_day = pd.Timestamp.today()
    model = MacroFactorsModel(signal_day)
    snapshot = model.build_snapshot()
    print(snapshot.to_agent_prompt())
