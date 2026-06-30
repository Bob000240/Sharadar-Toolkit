"""
Quality Strategy: high-quality compounders (profitability, stability, capital
discipline). S&P 500. Best late-cycle / risk-off / slowdowns. Signals:
sig_fundamentals (quality composite) + sig_events (risk).
"""

from __future__ import annotations
from datetime import date

import pandas as pd

from data.signals.sig_fundamentals import FundamentalsModel
from data.signals.sig_events import EventsModel
from decision_layer.det_layer.strategy import Strategy, ScreenResult

_MIN_QUALITY_PERCENTILE = 70.0
_MIN_QUALITY_PILLARS = 3

_EXCLUDING_EVENTS = {
    "delisting_risk",
    "bankruptcy",
    "restatement",
    "late_filing",
    "material_impairment",
}


def _score01(value, fallback=0.5) -> float:
    return float(value) / 100.0 if pd.notna(value) else fallback


class StratQuality(Strategy):
    NAME = "quality"
    PROFILE = {
        "description": "High-quality compounders on the S&P 500 (late-cycle tilt).",
        "universe": "SP500",
        "default_holding_days": 120,
        "max_position_pct": 0.06,
        "max_loss_pct": 0.12,
        "allowed_stop_ids": ["atr_2_5x", "pct_12"],
        "allowed_target_ids": ["rr_2", "pct_15"],
        "allowed_timeline_ids": ["trend_90d", "trend_120d"],
        "default_stop_id": "atr_2_5x",
        "default_target_id": "rr_2",
        "default_timeline_id": "trend_120d",
    }

    def screen(self, signal_day: date, tickers: list[str]) -> list[ScreenResult]:
        ts = pd.Timestamp(signal_day)
        prices = self._price_levels(signal_day, tickers)
        if prices.empty:
            return []
        present = prices.index.tolist()

        funds = FundamentalsModel(ts, present)
        scored = [t for t in present if t in funds.data.index]
        events = EventsModel(ts, scored)

        results: list[ScreenResult] = []
        for ticker in scored:
            f = funds.build_snapshot(ticker)
            ev = events.build_snapshot(ticker)

            ev_risks = ev.risk_flags()
            if any(ev_risks.get(code) for code in _EXCLUDING_EVENTS):
                continue

            f_risks = f.risk_flags()
            profitability = f.profitability()
            if not (
                f.quality_composite_percentile >= _MIN_QUALITY_PERCENTILE
                and f.valid_quality_pillars >= _MIN_QUALITY_PILLARS
                and profitability["fcf_positive"]
                and not f_risks["high_leverage"]
            ):
                continue

            row = prices.loc[ticker]
            gates = ["high_quality", "pillars_covered", "fcf_positive"]
            if profitability["roe_strong"]:
                gates.append("roe_strong")
            if f.balance_sheet_health()["low_leverage"]:
                gates.append("low_leverage")

            setup_score = min(
                1.0,
                0.70 * _score01(f.quality_composite_percentile)
                + 0.30 * _score01(f.roe_percentile),
            )

            results.append(
                ScreenResult(
                    symbol=ticker,
                    setup_score=setup_score,
                    passed_gates=gates,
                    risk_flags=[k for k, v in f_risks.items() if v],
                    entry_price=float(row["close"]),
                    atr=float(row["atr_14"]),
                    levels={"sma_50": float(row["sma_50"])},
                    signal_context={
                        "sector": f.sector,
                        "quality_composite_percentile": round(f.quality_composite_percentile, 2),
                        "valid_quality_pillars": int(f.valid_quality_pillars),
                        "quality_profitability_score": round(f.quality_profitability_score, 3)
                        if pd.notna(f.quality_profitability_score) else None,
                        "quality_safety_score": round(f.quality_safety_score, 3)
                        if pd.notna(f.quality_safety_score) else None,
                        "roe_percentile": round(f.roe_percentile, 2)
                        if pd.notna(f.roe_percentile) else None,
                        "roic": round(f.roic, 4) if pd.notna(f.roic) else None,
                        "de": round(f.de, 3) if pd.notna(f.de) else None,
                        "marketcap": round(f.marketcap, 0) if pd.notna(f.marketcap) else None,
                        "days_since_last_earnings": ev.days_since_last_earnings,
                    },
                )
            )
        return results


if __name__ == "__main__":
    strat = StratQuality()
    packets = strat.run(
        date(2024, 6, 28), tickers=["AAPL", "MSFT", "NVDA", "V", "MA", "COST", "UNH", "HD"], persist=False
    )
    print(f"{strat.NAME}: {len(packets)} candidates")
    for p in packets:
        print(
            f"  {p['symbol']:6s} score={p['setup_score']:.3f} entry={p['entry_price']} "
            f"stop={p['default_stop_id']} target={p['default_target_id']} gates={p['passed_gates']}"
        )
