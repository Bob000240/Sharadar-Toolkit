"""
Momentum Strategy: relative-strength / trend continuation on liquid US equities
(mid-cap and established small-cap, qualifying large caps eligible). Best in
persistent trends, mid-cycle, low/falling vol.

Research basis (see PROJECT_IMPLEMENTATION.md § Momentum):
  - Relative-strength momentum (Jegadeesh & Titman 1993): past 12-month winners
    keep winning. Measured on the intermediate/long horizon and DELIBERATELY
    skipping the most recent month (return_20d), whose <=1-month component
    reverses (Jegadeesh 1990; Novy-Marx 2012). Lives in the trend-continuation
    entry mode, keyed on 60d/252d return ranks, not 20d.
  - 52-week-high (George & Hwang 2004): a fresh 52-week high is a distinct,
    separately-published signal — its own entry mode, and it need not be
    top-quintile on trailing returns.
  - Industry momentum (Moskowitz & Grinblatt 1999): leading-sector tilt.

The screen is general momentum eligibility (liquid, primary uptrend, confirmed
trend); the two entry modes carry the specific momentum thesis, so they admit
different names (a candidate may qualify for both). Signals: sig_technicals +
sig_sector_rotation (context) + sig_events (risk).
"""

from __future__ import annotations
from datetime import date

import pandas as pd

from data.signals.sig_technicals import TechnicalsModel
from data.signals.sig_sector_rotation import SectorRotationModel
from data.signals.sig_events import EventsModel
import database.market.fundamentals_repo as fundamentals_repo
from set_up.config import ETF_SECTOR_MAP, cap_bucket, get_stock_symbols
from decision_layer.det_layer.strategy import Strategy, ScreenResult

_BENCHMARK = "SPY"
_ETFS = list(ETF_SECTOR_MAP.keys())

# Momentum spans small/mid/large (nano/micro dropped by cap_bucket). Mega-cap
# giants stay eligible but carry a crowding risk_flag rather than a universe cut:
# the premium is thin and crash risk concentrates there, so surface it for the
# risk layer instead of dropping the name outright.
_ALLOWED_CAPS = {"small", "mid", "large"}
# Mega-cap crowding line (~$200B). Eligible, but flagged for the risk layer.
_MEGA_CAP_THRESHOLD = 200_000_000_000

_MIN_DOLLAR_VOLUME = 5_000_000
# 12-month momentum, top quintile within the ranked universe (Jegadeesh-Titman
# 1993 used the top decile; band is CALIBRATION, the rank basis is cited).
_MIN_RETURN_252D_PCTILE = 80.0
# Intermediate horizon must corroborate (Novy-Marx 2012). CALIBRATION band.
_MIN_RETURN_60D_PCTILE = 70.0
# 52-week-high breakout confirmation: volume-surge multiple over average. CALIBRATION.
_VOLUME_SURGE = 1.5
# Leading sector = top-3 of 11 sectors by 20d return (Moskowitz-Grinblatt tilt). CALIBRATION.
_LEADING_SECTOR_RANK = 3

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
        "description": "Relative-strength / trend-continuation on liquid US equities.",
        "universe": "US_EQUITY",
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

    def _entry_modes(self, t) -> dict[str, bool]:
        """Two research-distinct entry paths; a candidate must confirm through at
        least one (it may qualify for both). The screen establishes general
        momentum eligibility; each mode carries a *different* momentum thesis, so
        they admit different names."""
        return {
            # Jegadeesh-Titman relative strength: top-quintile 12-month momentum with
            # intermediate corroboration (skip-a-month — not gating on the
            # reversal-prone recent month, Novy-Marx 2012), above the 50-day, with
            # broad multi-horizon strength.
            "trend_continuation": (
                t.return_252d_percentile >= _MIN_RETURN_252D_PCTILE
                and t.return_60d_percentile >= _MIN_RETURN_60D_PCTILE
                and t.above_sma_50
                and t.momentum_consistency >= 3
            ),
            # George-Hwang (2004) 52-week-high, as a CONFIRMED breakout: a fresh
            # 52-week high (below->above transition), not merely near one, on a
            # volume surge with bullish MA structure. A distinct signal that need
            # NOT be top-quintile on trailing returns (e.g. a breakout from a long
            # base). Overbought is not filtered — a genuine breakout is expected to
            # be strong; it stays visible in risk_flags for the risk layer.
            "52w_high_breakout": (
                t.new_52w_high
                and t.volume_ratio > _VOLUME_SURGE
                and t.sma_20 > t.sma_50
            ),
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
        # Point-in-time market cap for the size gate. Momentum uses only technicals,
        # so pull marketcap via the slim per-ticker latest-ART lookup (not the full
        # FundamentalsModel). Names without a fundamentals row are dropped by the cap
        # gate below — can't verify size, so exclude.
        mcaps = (
            fundamentals_repo.get_latest(present, "ART", ts)
            .set_index("ticker")["marketcap"]
            .to_dict()
        )

        results: list[ScreenResult] = []
        for ticker in present:
            t = tech.build_snapshot(ticker)
            ev = events.build_snapshot(ticker)

            ev_risks = ev.risk_flags()
            if any(ev_risks.get(code) for code in _EXCLUDING_EVENTS):
                continue

            mcap = mcaps.get(ticker)
            cap = cap_bucket(mcap)
            if cap not in _ALLOWED_CAPS:
                continue

            # ── Screen: general momentum eligibility (liquid, primary uptrend,
            # confirmed trend). The specific momentum thesis lives in the entry
            # modes below, so the two modes admit different names. ──
            liquid = t.dollar_volume_20d_avg >= _MIN_DOLLAR_VOLUME
            uptrend = t.above_sma_200
            trend_confirmed = t.slope_x_r2 > 0
            if not (liquid and uptrend and trend_confirmed):
                continue

            # Must confirm through at least one research-distinct entry mode.
            modes = self._entry_modes(t)
            if not any(modes.values()):
                continue

            sec = sectors.build_snapshot(ticker, t.sector)

            gates = ["liquid", "uptrend", "trend_confirmed", f"{cap}_cap"]
            gates += [f"mode_{name}" for name, passed in modes.items() if passed]
            if sec.sector_rank_20d is not None and sec.sector_rank_20d <= _LEADING_SECTOR_RANK:
                gates.append("leading_sector")  # Moskowitz-Grinblatt 1999 (top-3 sector)

            # Score = intermediate/long momentum rank + leading-sector tilt.
            setup_score = min(
                1.0,
                0.50 * (t.return_252d_percentile / 100.0)
                + 0.30 * (t.return_60d_percentile / 100.0)
                + 0.20 * sec.sector_score(),
            )

            risk_flags = [k for k, v in t.risk_flags().items() if v]
            risk_flags += [
                k for k, v in ev_risks.items() if v and k in ("just_reported", "post_earnings")
            ]
            if mcap is not None and mcap >= _MEGA_CAP_THRESHOLD:
                risk_flags.append("mega_cap_crowding")  # eligible, but crowded (see note above)

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
    
    def risk_controls(self, packet: dict) -> list[str]:
        return packet.get("risk_flags", [])


if __name__ == "__main__":
    strat = StratMomentum()
    as_of = date.today()
    packets = strat.run(as_of, tickers=get_stock_symbols(), persist=False, top_n=5)
    print(f"{strat.NAME} ({as_of}): top {len(packets)} of the full passing set")
    for p in packets:
        print(
            f"  {p['symbol']:6s} score={p['setup_score']:.3f} "
            f"entry={p['entry_price']} stop={p['default_stop_id']} "
            f"target={p['default_target_id']} gates={p['passed_gates']}"
        )
