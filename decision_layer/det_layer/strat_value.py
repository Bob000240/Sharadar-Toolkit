"""
Value Strategy: sector-relative deep value with a Piotroski health filter to
avoid value traps, on liquid US equities (ex Financials/REITs in v1). Best
early-cycle / reflation.

Research basis (see PROJECT_IMPLEMENTATION.md § Value):
  - Value premium (Fama & French 1992/1993; Basu 1977): cheap stocks outperform.
    Cheapness is the sector-ranked composite of earnings yield (E/P), FCF yield,
    EV/EBITDA yield (Loughran & Wellman 2011), book yield (B/M), and sales yield;
    top 30% cheapest in sector qualifies.
  - Value-trap filter (Piotroski 2000): among cheap stocks, require the fundamentals
    to be healthy — operating cash flow > 0 and earnings backed by cash (CFO > net
    income, i.e. low accruals; Sloan 1996). This is the screen's core differentiator.

Entry is a single deterministic gate — scheduled rank admission at rebalance.
Value is a periodic cross-sectional rank sort, so no market-timing overlay.
Signals: sig_fundamentals + sig_events.
"""

from __future__ import annotations
from datetime import date

import pandas as pd

from data.signals.sig_fundamentals import FundamentalsModel
from data.signals.sig_events import EventsModel
from decision_layer.det_layer.strategy import Strategy, ScreenResult
from set_up.config import cap_bucket, get_stock_symbols

# Cheapest 30% within sector on the value composite (Fama-French / Asness). Rank-based.
_MIN_VALUE_PERCENTILE = 70.0
# Composite needs at least 2 valid yield measures to be trustworthy.
_MIN_VALUE_METRICS = 2

# Value spans small/mid/large caps (nano/micro excluded by cap_bucket).
_ALLOWED_CAPS = {"small", "mid", "large"}

# Excluded in v1 until dedicated sector metrics exist for these business models.
_EXCLUDED_SECTORS = {"Financial Services", "Real Estate"}

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
        "description": "Sector-relative deep value with a Piotroski trap filter.",
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
            if f.sector in _EXCLUDED_SECTORS:
                continue
            cap = cap_bucket(f.marketcap)
            if cap not in _ALLOWED_CAPS:
                continue
            ev = events.build_snapshot(ticker)
            if any(ev.risk_flags().get(code) for code in _EXCLUDING_EVENTS):
                continue

            f_risks = f.risk_flags()

            # ── Value screen: cheap (rank) + Piotroski health filter (traps) ──
            if not (
                # Cheapest 30% within sector on the value composite — earnings/FCF/
                # EV-EBITDA/book/sales yields (Fama-French 1992; Loughran-Wellman 2011).
                # Need >= 2 valid yield measures to trust the composite.
                f.valid_value_metrics >= _MIN_VALUE_METRICS
                and f.value_composite_percentile >= _MIN_VALUE_PERCENTILE
                # Piotroski 2000: operating cash flow positive (not a distress trap).
                and f.ncfo > 0
                # Sloan 1996 / Piotroski: CFO > net income => earnings cash-backed.
                and f.accrual_quality > 0
            ):
                continue
            # Hard safety reject: broad deterioration, or cash burn under leverage.
            if f_risks["combined_deterioration"] or (
                f_risks["cash_burn"] and f_risks["high_leverage"]
            ):
                continue

            row = prices.loc[ticker]
            # Entry = scheduled rank admission: a passing name enters at the next
            # rebalance. Value is a periodic rank sort, so one deterministic entry.
            gates = ["deep_value", "value_metrics", "cash_earnings", "low_accruals",
                     "rebalance_admission", f"{cap}_cap"]
            if f.divyield > 0:
                gates.append("dividend_payer")

            # The value composite rank IS the value score (single source of truth).
            setup_score = _score01(f.value_composite_percentile)

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
                        "accrual_quality": round(f.accrual_quality, 4)
                        if pd.notna(f.accrual_quality) else None,
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
    

    def risk_controls(self, packet: dict) -> list[str]:
        return packet.get("risk_flags", [])


if __name__ == "__main__":
    strat = StratValue()
    as_of = date.today()
    packets = strat.run(as_of, tickers=get_stock_symbols(), persist=False, top_n=5)
    print(f"{strat.NAME} ({as_of}): top {len(packets)} of the full passing set")
    for p in packets:
        print(
            f"  {p['symbol']:6s} score={p['setup_score']:.3f} entry={p['entry_price']} "
            f"stop={p['default_stop_id']} target={p['default_target_id']} gates={p['passed_gates']}"
        )
