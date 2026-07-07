"""
Quality Strategy: high-quality compounders on liquid US equities (ex
Financials/REITs in v1). Best late-cycle / risk-off / slowdowns.

Research basis (see PROJECT_IMPLEMENTATION.md § Quality):
  - Quality-Minus-Junk (Asness, Frazzini & Pedersen 2019): a stock's quality is
    the sector-ranked composite of four pillars — profitability, growth, safety,
    payout. `quality_composite_percentile` is that rank; top 30% qualifies.
  - Gross profitability (Novy-Marx 2013): gross profits / assets leads the
    profitability pillar.
  - Piotroski (2000): operating cash flow > 0 (earnings are real).
  - Accruals anomaly (Sloan 1996): CFO > net income (earnings backed by cash).

Entry is a single deterministic gate — scheduled rank admission at rebalance.
Factor portfolios are periodic rank sorts with no market-timing overlay, so
quality has no separate entry mode. Signals: sig_fundamentals + sig_events.
"""

from __future__ import annotations
from datetime import date

import pandas as pd

from data.signals.sig_fundamentals import FundamentalsModel
from data.signals.sig_events import EventsModel
from decision_layer.det_layer.strategy import Strategy, ScreenResult
from set_up.config import cap_bucket, get_stock_symbols

# QMJ composite top-30% within sector (Asness/Frazzini/Pedersen 2019). Rank-based.
_MIN_QUALITY_PERCENTILE = 70.0
# Require at least 3 of the 4 QMJ pillars to have enough data to score.
_MIN_QUALITY_PILLARS = 3
# Soft-gate context labels appended to passed_gates (not hard gates). CALIBRATION.
_ROE_STRONG = 0.15  # strong profitability (QMJ / Novy-Marx context)
_LOW_LEVERAGE_DE = 1.0  # conservative balance sheet; distinct from the de<=2 hard floor

# Quality is a mid/large-cap factor (small/nano/micro excluded).
_ALLOWED_CAPS = {"mid", "large"}

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


class StratQuality(Strategy):
    NAME = "quality"
    PROFILE = {
        "description": "High-quality compounders on liquid US equities (late-cycle tilt).",
        "universe": "US_EQUITY",
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

    def _rank_key(self, packet: dict):
        # setup_score is a within-sector percentile and saturates at 1.0 for each
        # sector's leader, so the top-N would be an arbitrary slice of the ties.
        # Break ties by the raw QMJ composite → a deterministic set of the strongest
        # sector leaders (sector-spread, not one hot sector).
        ctx = packet["signal_context"]
        return (packet["setup_score"], ctx.get("quality_composite_score") or 0.0)

    def screen(self, signal_day: date, tickers: list[str]) -> list[ScreenResult]:
        ts = pd.Timestamp(signal_day)
        prices = self._price_levels(signal_day, tickers)
        if prices.empty:
            return []
        present = prices.index.tolist()

        fundamentals = FundamentalsModel(ts, present)
        scored = [t for t in present if t in fundamentals.data.index]
        events = EventsModel(ts, scored)

        results: list[ScreenResult] = []
        for ticker in scored:
            f = fundamentals.build_snapshot(ticker)
            if f.sector in _EXCLUDED_SECTORS:
                continue
            cap = cap_bucket(f.marketcap)
            if cap not in _ALLOWED_CAPS:
                continue
            ev = events.build_snapshot(ticker)
            if any(ev.risk_flags().get(code) for code in _EXCLUDING_EVENTS):
                continue

            f_risks = f.risk_flags()

            # ── Quality screen: QMJ composite + earnings-quality floors ──
            if not (
                # QMJ sector-ranked composite (profitability + growth + safety +
                # payout), top 30%. Profitability pillar led by gross profits /
                # assets (Novy-Marx 2013).
                f.quality_composite_percentile >= _MIN_QUALITY_PERCENTILE
                and f.valid_quality_pillars >= _MIN_QUALITY_PILLARS
                # Piotroski 2000: operating cash flow positive (earnings are real).
                # CFO, not FCF — a capex-heavy compounder can have FCF<0 with
                # strong operating cash flow; matches Value's identical floor.
                and f.ncfo > 0
                # Sloan 1996: CFO > net income => low accruals, earnings cash-backed.
                and f.accrual_quality > 0
                # Safety floor: exclude extreme leverage (de > 2). CALIBRATION.
                and not f_risks["high_leverage"]
            ):
                continue

            row = prices.loc[ticker]
            # Entry = scheduled rank admission: a passing name enters at the next
            # rebalance. QMJ is a periodic rank sort, so there is one entry gate.
            gates = [
                "quality_composite",
                "cash_earnings",
                "low_accruals",
                "rebalance_admission",
                f"{cap}_cap",
            ]
            if f.roe > _ROE_STRONG:
                gates.append("roe_strong")
            if f.de < _LOW_LEVERAGE_DE:
                gates.append("low_leverage")

            # The QMJ composite rank IS the quality score (single source of truth).
            setup_score = _score01(f.quality_composite_percentile)

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
                        "quality_composite_percentile": round(
                            f.quality_composite_percentile, 2
                        ),
                        "quality_composite_score": round(f.quality_composite_score, 3)
                        if pd.notna(f.quality_composite_score)
                        else None,
                        "valid_quality_pillars": int(f.valid_quality_pillars),
                        "quality_profitability_score": round(
                            f.quality_profitability_score, 3
                        )
                        if pd.notna(f.quality_profitability_score)
                        else None,
                        "quality_safety_score": round(f.quality_safety_score, 3)
                        if pd.notna(f.quality_safety_score)
                        else None,
                        "accrual_quality": round(f.accrual_quality, 4)
                        if pd.notna(f.accrual_quality)
                        else None,
                        "roe_percentile": round(f.roe_percentile, 2)
                        if pd.notna(f.roe_percentile)
                        else None,
                        "roic": round(f.roic, 4) if pd.notna(f.roic) else None,
                        "de": round(f.de, 3) if pd.notna(f.de) else None,
                        "marketcap": round(f.marketcap, 0)
                        if pd.notna(f.marketcap)
                        else None,
                        "days_since_last_earnings": ev.days_since_last_earnings,
                    },
                )
            )
        return results

    def risk_controls(self, packet: dict) -> list[str]:
        return packet.get("risk_flags", [])


if __name__ == "__main__":
    strat = StratQuality()
    as_of = date.today()
    packets = strat.run(as_of, tickers=get_stock_symbols(), persist=False, top_n=5)
    print(f"{strat.NAME}: top {len(packets)} of the full passing set")
    for p in packets:
        print(
            f"  {p['symbol']:6s} score={p['setup_score']:.3f} entry={p['entry_price']} "
            f"stop={p['default_stop_id']} target={p['default_target_id']} gates={p['passed_gates']}"
        )
