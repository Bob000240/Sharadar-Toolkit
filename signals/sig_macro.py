import pandas as pd
from dataclasses import dataclass


@dataclass
class MacroSnapshot:
    signal_day: pd.Timestamp

    # Market regime
    spy_above_200d_ma: bool
    vix_level: float
    vix_percentile_1y: float             # 0.0–1.0; where current VIX sits vs trailing 252 trading days
    market_breadth_pct_above_200d: float # fraction of S&P 500 stocks above their 200d MA (0.0–1.0)

    # Rates & credit
    yield_10y: float                     # 10-year Treasury yield
    yield_curve_2y10y: float             # 10Y minus 2Y; negative = inverted = late-cycle
    hy_credit_spread: float              # high-yield OAS in bps; widening = risk-off, flight to quality

    # Defensive sector rotation
    defensive_rel_strength_20d: float    # avg excess return of XLV + XLP + XLU vs SPY over 20d
    defensive_rel_strength_60d: float    # same over 60d; persistent = structural rotation into defensives

    # Market-wide earnings revision context
    sp500_revision_breadth: float        # fraction of S&P 500 stocks with positive EPS revisions (0.0–1.0)

    def to_agent_prompt(self) -> str:
        def pct(v: float) -> str:
            return f"{v:+.1%}"

        def bps(v: float) -> str:
            return f"{v:.0f}bps"

        regime = "RISK-ON" if self.spy_above_200d_ma else "RISK-OFF"
        vix_context = (
            "elevated" if self.vix_percentile_1y > 0.7
            else "low" if self.vix_percentile_1y < 0.3
            else "moderate"
        )
        curve_context = "INVERTED (late-cycle)" if self.yield_curve_2y10y < 0 else "normal"
        breadth_context = (
            "weak" if self.market_breadth_pct_above_200d < 0.4
            else "strong" if self.market_breadth_pct_above_200d > 0.65
            else "mixed"
        )
        defensive_bias = (
            "rotating INTO defensives" if self.defensive_rel_strength_20d > 0
            else "rotating OUT of defensives"
        )

        lines = [
            f"MACRO SNAPSHOT | Signal date: {self.signal_day}",
            "",
            "--- MARKET REGIME ---",
            f"  SPY vs 200d MA:  {regime}  (SPY {'above' if self.spy_above_200d_ma else 'below'} long-term trend)",
            f"  VIX level:       {self.vix_level:.1f}  ({vix_context}, {self.vix_percentile_1y:.0%} percentile vs trailing year)",
            f"  Market breadth:  {self.market_breadth_pct_above_200d:.0%} of S&P 500 above 200d MA  ({breadth_context})",
            "",
            "--- RATES & CREDIT ---",
            f"  10Y Treasury yield:    {self.yield_10y:.2%}",
            f"  Yield curve (10Y-2Y):  {self.yield_curve_2y10y:+.2%}  ({curve_context})",
            f"  HY credit spread:      {bps(self.hy_credit_spread)}  (wide = risk-off; quality stocks benefit)",
            "",
            "--- DEFENSIVE ROTATION ---",
            f"  20d defensive vs SPY:  {pct(self.defensive_rel_strength_20d)}  ({defensive_bias} short-term)",
            f"  60d defensive vs SPY:  {pct(self.defensive_rel_strength_60d)}  (persistent = structural shift)",
            "",
            "--- EARNINGS REVISION CONTEXT ---",
            f"  S&P 500 revision breadth:  {self.sp500_revision_breadth:.0%} of stocks with positive EPS revisions",
            f"  (interpret individual stock revisions against this market-wide baseline)",
        ]
        return "\n".join(lines)
