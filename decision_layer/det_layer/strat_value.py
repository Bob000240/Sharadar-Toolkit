"""
Value Strategy: sector-relative deep value with a quality floor to avoid value
traps. Broad universe. Best early-cycle / reflation, rising rates, steepening
curve. Signals: sig_fundamentals (value composite) + sig_events (risk).
"""

from __future__ import annotations
from datetime import date

import pandas as pd

from data.signals.sig_fundamentals import FundamentalsModel
from data.signals.sig_events import EventsModel
from decision_layer.det_layer.strategy import Strategy, ScreenResult

_MIN_VALUE_PERCENTILE = 70.0
_MIN_VALUE_METRICS = 2

_EXCLUDING_EVENTS = {
    "delisting_risk",
    "bankruptcy",
    "restatement",
    "late_filing",
    "material_impairment",
}


def _score01(value, fallback=0.5) -> float:
    return float(value) / 100.0 if pd.notna(value) else fallback


class StratValue(Strategy):
    NAME = "value"
    PROFILE = {
        "description": "Sector-relative deep value with a quality-floor trap guard.",
        "universe": "US_EQUITY",
        "default_holding_days": 120,
        "max_position_pct": 0.05,
        "max_loss_pct": 0.15,
        "allowed_stop_ids": ["pct_15", "atr_3x"],
        "allowed_target_ids": ["pct_25", "rr_2"],
        "allowed_timeline_ids": ["trend_90d", "trend_120d"],
        "default_stop_id": "pct_15",
        "default_target_id": "pct_25",
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
            if f_risks["combined_deterioration"] or (
                f_risks["cash_burn"] and f_risks["high_leverage"]
            ):
                continue

            valuation = f.valuation()
            profitability = f.profitability()
            quality_floor = profitability["fcf_positive"] or profitability["roe_positive"]
            if not (
                valuation["enough_value_metrics"]
                and f.value_composite_percentile >= _MIN_VALUE_PERCENTILE
                and quality_floor
            ):
                continue

            row = prices.loc[ticker]
            gates = ["deep_value", "value_metrics", "quality_floor"]
            if valuation["pays_dividend"]:
                gates.append("dividend_payer")
            if valuation["large_cap"]:
                gates.append("large_cap")
            elif valuation["mid_cap"]:
                gates.append("mid_cap")

            setup_score = min(
                1.0,
                0.75 * _score01(f.value_composite_percentile)
                + 0.25 * _score01(f.quality_composite_percentile),
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
                        "value_composite_percentile": round(f.value_composite_percentile, 2),
                        "valid_value_metrics": int(f.valid_value_metrics),
                        "earnings_yield": round(f.earnings_yield, 4)
                        if pd.notna(f.earnings_yield) else None,
                        "fcf_yield": round(f.fcf_yield, 4) if pd.notna(f.fcf_yield) else None,
                        "quality_composite_percentile": round(f.quality_composite_percentile, 2)
                        if pd.notna(f.quality_composite_percentile) else None,
                        "de": round(f.de, 3) if pd.notna(f.de) else None,
                        "divyield": round(f.divyield, 4) if pd.notna(f.divyield) else None,
                        "marketcap": round(f.marketcap, 0) if pd.notna(f.marketcap) else None,
                        "days_since_last_earnings": ev.days_since_last_earnings,
                    },
                )
            )
        return results


if __name__ == "__main__":
    strat = StratValue()
    packets = strat.run(
        date(2024, 6, 28), tickers=["JPM", "XOM", "F", "GM", "C", "PFE", "VZ", "T"], persist=False
    )
    print(f"{strat.NAME}: {len(packets)} candidates")
    for p in packets:
        print(
            f"  {p['symbol']:6s} score={p['setup_score']:.3f} entry={p['entry_price']} "
            f"stop={p['default_stop_id']} target={p['default_target_id']} gates={p['passed_gates']}"
        )
