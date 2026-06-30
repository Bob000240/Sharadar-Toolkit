"""
Momentum Strategy (repairs the old pre_RS): relative-strength / trend
continuation on the S&P 500. Best in persistent trends, mid-cycle, low/falling
vol. Signals: sig_technicals (+ sig_sector_rotation context, sig_events risk).
"""

from __future__ import annotations
from datetime import date

import pandas as pd

from data.signals.sig_technicals import TechnicalsModel
from data.signals.sig_sector_rotation import SectorRotationModel
from data.signals.sig_events import EventsModel
from set_up.config import ETF_SECTOR_MAP
from decision_layer.det_layer.strategy import Strategy, ScreenResult

_BENCHMARK = "SPY"
_ETFS = list(ETF_SECTOR_MAP.keys())

# Gate thresholds
_MIN_DOLLAR_VOLUME = 5_000_000
_MIN_MOMENTUM_SCORE = 0.55
_MIN_RETURN_20D_PCTILE = 60.0

# Event codes that disqualify a name outright.
_EXCLUDING_EVENTS = {
    "delisting_risk",
    "bankruptcy",
    "restatement",
    "late_filing",
    "material_impairment",
}


class StratMomentum(Strategy):
    NAME = "momentum"
    PROFILE = {
        "description": "Relative-strength / trend-continuation on the S&P 500.",
        "universe": "SP500",
        "default_holding_days": 90,
        "max_position_pct": 0.05,
        "max_loss_pct": 0.10,
        "allowed_stop_ids": ["atr_2_5x", "atr_3x", "pct_12"],
        "allowed_target_ids": ["rr_2", "rr_3", "pct_25"],
        "allowed_timeline_ids": ["position_60d", "trend_90d", "trend_120d"],
        "default_stop_id": "atr_2_5x",
        "default_target_id": "rr_3",
        "default_timeline_id": "trend_90d",
    }

    def screen(self, signal_day: date, tickers: list[str]) -> list[ScreenResult]:
        ts = pd.Timestamp(signal_day)
        # Restrict to names that actually have indicators (avoids aborting the
        # whole screen on a single name the universe lists but we haven't loaded).
        present = self._price_levels(signal_day, tickers).index.tolist()
        if not present:
            return []

        tech = TechnicalsModel(ts, present, _BENCHMARK, _ETFS)
        sectors = SectorRotationModel(ts)
        events = EventsModel(ts, present)

        results: list[ScreenResult] = []
        for ticker in present:
            t = tech.build_snapshot(ticker)
            ev = events.build_snapshot(ticker)

            ev_risks = ev.risk_flags()
            if any(ev_risks.get(code) for code in _EXCLUDING_EVENTS):
                continue

            # ── Core gates ──
            liquid = t.dollar_volume_20d_avg >= _MIN_DOLLAR_VOLUME
            uptrend = t.above_sma_200
            momentum = (
                t.momentum_score() >= _MIN_MOMENTUM_SCORE
                or t.return_20d_percentile >= _MIN_RETURN_20D_PCTILE
            )
            trend_confirmed = t.trend_linearity()["trend_confirmed"]
            if not (liquid and uptrend and momentum and trend_confirmed):
                continue

            sec = sectors.build_snapshot(ticker, t.sector)

            gates = ["liquid", "uptrend", "momentum", "trend_confirmed"]
            if t.above_sma_50 and t.momentum_consistency >= 3:
                gates.append("trend_continuation")
            if t.breakout_context()["within_3pct_20d_high"] or t.new_52w_high:
                gates.append("breakout")
            if sec.market_regime()["in_leading_sector"]:
                gates.append("leading_sector")

            setup_score = min(
                1.0,
                0.55 * t.momentum_score()
                + 0.25 * sec.sector_score()
                + 0.20 * (t.return_20d_percentile / 100.0),
            )

            risk_flags = [k for k, v in t.risk_flags().items() if v]
            risk_flags += [
                k for k, v in ev_risks.items() if v and k in ("just_reported", "post_earnings")
            ]

            results.append(
                ScreenResult(
                    symbol=ticker,
                    setup_score=setup_score,
                    passed_gates=gates,
                    risk_flags=risk_flags,
                    entry_price=t.price,
                    atr=t.atr_14,
                    levels={"sma_50": t.sma_50},
                    signal_context={
                        "momentum_score": round(t.momentum_score(), 4),
                        "return_20d_percentile": round(t.return_20d_percentile, 2),
                        "return_60d_percentile": round(t.return_60d_percentile, 2),
                        "return_252d_percentile": round(t.return_252d_percentile, 2),
                        "sector": t.sector,
                        "sector_rank_20d": sec.sector_rank_20d,
                        "sector_score": round(sec.sector_score(), 4),
                        "rsi_14": round(t.rsi_14, 2),
                        "pct_from_52w_high": round(t.pct_from_52w_high, 4),
                        "trend_slope_60d": round(t.trend_slope_60d, 6),
                        "r_squared_60d": round(t.r_squared_60d, 4),
                        "dollar_volume_20d_avg": round(t.dollar_volume_20d_avg, 0),
                        "days_since_last_earnings": ev.days_since_last_earnings,
                    },
                )
            )
        return results


if __name__ == "__main__":
    strat = StratMomentum()
    packets = strat.run(date(2024, 6, 28), tickers=["AAPL", "MSFT", "NVDA", "JPM", "XOM"], persist=False)
    print(f"{strat.NAME}: {len(packets)} candidates")
    for p in packets:
        print(
            f"  {p['symbol']:6s} score={p['setup_score']:.3f} "
            f"entry={p['entry_price']} stop={p['default_stop_id']} "
            f"target={p['default_target_id']} gates={p['passed_gates']}"
        )
