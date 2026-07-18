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
  - Exits: momentum's thesis IS the trend, so the deterministic exit is a
    trailing stop plus a primary-uptrend break (both THESIS_INVALIDATED), under
    the universal max-loss floor (MAXIMUM_LOSS_BREACH). Stop-loss evidence:
    Han, Zhou & Zhu 2016 (stops tame momentum crashes); trailing beats
    entry-anchored stops with 15-20% most effective, evaluated at run cadence
    rather than intraday.

Structure: two per-strategy processors. MomentumEntryScreener (buy side) screens
a universe point-in-time and emits CandidateSnapshots; MomentumExitMonitor (sell
side) evaluates open positions and emits ExitSnapshots. The portfolio manager
owns signal_day, ranking, dedupe, sizing, persistence, and execution prices.
CONCERNING_EVENTS is the agent's exit, not produced here.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from data.signals.sig_technicals import TechnicalsModel
from data.signals.sig_sector_rotation import SectorRotationModel
from data.signals.sig_events import EventsModel
from data.signals.sig_fundamentals import load_marketcaps
from set_up.config import ETF_SECTOR_MAP, cap_bucket, get_stock_symbols
import database.operational.strategy_profiles_repository as profiles_repo


# ── records: one per symbol ──────────────────────────────────────────────────
# Shared contracts. Lift these (and the two bases below) into a shared module
# when strat_value / strat_quality are rebuilt, so all three strategies and the
# orchestrator import one CandidateSnapshot type.

@dataclass
class CandidateSnapshot:
    symbol: str
    entry_date: date              # the signal_day this candidate was screened
    setup_score: float
    passed_gates: list[str]
    risk_flags: list[str]
    signal_context: dict          # the numbers behind the pass


@dataclass
class ExitSnapshot:
    symbol: str
    exit_date: date               # the signal_day the exit condition fired
    exit_reason: str              # MAXIMUM_LOSS_BREACH / THESIS_INVALIDATED / CONCERNING_EVENTS
    exit_context: dict            # which rule fired, values, agent citation


# ── processors: one per strategy ─────────────────────────────────────────────

class EntryScreener:
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.profile = profiles_repo.get_profile_by_name(strategy_name)
        if self.profile is None:
            raise RuntimeError(
                f"Strategy profile {strategy_name!r} is missing; run set_up.setup_db"
            )

    def run(self, symbols: list[str], signal_day: date) -> list[CandidateSnapshot]:
        raise NotImplementedError


class ExitMonitor:
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.profile = profiles_repo.get_profile_by_name(strategy_name)
        if self.profile is None:
            raise RuntimeError(
                f"Strategy profile {strategy_name!r} is missing; run set_up.setup_db"
            )

    def run(self, positions: list[dict], signal_day: date) -> list[ExitSnapshot]:
        raise NotImplementedError


# ── momentum calibration ─────────────────────────────────────────────────────

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

# Trailing stop: drawdown from the position's high-water mark that invalidates
# the trend thesis. 15-20% is the effective band in the stop-loss literature,
# with trailing beating entry-anchored stops; evaluated at run cadence, not
# intraday (prevents over-trading). CALIBRATION within the cited band.
_TRAILING_STOP_DRAWDOWN = 0.20

# Event codes that disqualify a name outright.
_EXCLUDING_EVENTS = {
    "delisting_risk",
    "bankruptcy",
    "restatement",
    "late_filing",
    "material_impairment",
}


class MomentumEntryScreener(EntryScreener):
    """Buy side. Screen = general momentum eligibility (liquid, primary uptrend,
    confirmed trend); the momentum thesis lives in two research-distinct entry
    modes, so they admit different names (a candidate may qualify for both)."""

    def __init__(self):
        super().__init__("momentum")

    def _entry_modes(self, t) -> dict[str, bool]:
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

    def run(self, symbols: list[str], signal_day: date) -> list[CandidateSnapshot]:
        ts = pd.Timestamp(signal_day)
        # No pre-filter: build_technical_signals() raises if any symbol lacks an
        # indicator row as of signal_day (e.g. update_indicators() hasn't caught
        # up to a newly-liquid universe addition yet). Accepted as-is.
        present = symbols

        tech = TechnicalsModel(ts, present, _BENCHMARK, _ETFS)
        sectors = SectorRotationModel(ts)
        events = EventsModel(ts, present)
        mcaps = load_marketcaps(present, ts)

        candidates: list[CandidateSnapshot] = []
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
            if (
                sec.sector_rank_20d is not None
                and sec.sector_rank_20d <= _LEADING_SECTOR_RANK
            ):
                gates.append(
                    "leading_sector"
                )  # Moskowitz-Grinblatt 1999 (top-3 sector)

            # Score = intermediate/long momentum rank + leading-sector tilt.
            setup_score = min(
                1.0,
                0.50 * (t.return_252d_percentile / 100.0)
                + 0.30 * (t.return_60d_percentile / 100.0)
                + 0.20 * sec.sector_score(),
            )

            risk_flags = [k for k, v in t.risk_flags().items() if v]
            risk_flags += [
                k
                for k, v in ev_risks.items()
                if v and k in ("just_reported", "post_earnings")
            ]
            if mcap is not None and mcap >= _MEGA_CAP_THRESHOLD:
                risk_flags.append(
                    "mega_cap_crowding"
                )  # eligible, but crowded (see note above)

            candidates.append(
                CandidateSnapshot(
                    symbol=ticker,
                    entry_date=signal_day,
                    setup_score=setup_score,
                    passed_gates=gates,
                    risk_flags=risk_flags,
                    signal_context={
                        "price": round(t.price, 4),
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
        return candidates


class MomentumExitMonitor(ExitMonitor):
    """Sell side. Deterministic exits only, first match wins, max-loss first
    (universal floor takes precedence). Expected position keys: "symbol",
    "entry_price" (actual fill, required), "high_water_mark" (optional until the
    position store is settled — the trailing stop is skipped without it).

    A held symbol with no indicator row is skipped (held): no price means no
    deterministic verdict — a data gap for the agent's watchlist, not a rule.
    """

    def __init__(self):
        super().__init__("momentum")

    def run(self, positions: list[dict], signal_day: date) -> list[ExitSnapshot]:
        if not positions:
            return []
        ts = pd.Timestamp(signal_day)
        symbols = [p["symbol"] for p in positions]
        rows = TechnicalsModel.price_levels(symbols, ts)
        if rows.empty:
            return []
        max_loss_pct = float(self.profile["max_loss_pct"])

        exits: list[ExitSnapshot] = []
        for pos in positions:
            symbol = pos["symbol"]
            if symbol not in rows.index:
                continue  # no market data — hold; agent territory
            row = rows.loc[symbol]
            close = float(row["close"])
            entry_price = float(pos["entry_price"])

            # 1. Universal max-loss floor. Cause-agnostic: budgeted loss is
            # exceeded, exit regardless of thesis. Cannot be overridden.
            pnl_pct = close / entry_price - 1
            if pnl_pct <= -max_loss_pct:
                exits.append(
                    ExitSnapshot(
                        symbol=symbol,
                        exit_date=signal_day,
                        exit_reason="MAXIMUM_LOSS_BREACH",
                        exit_context={
                            "rule": "universal_max_loss",
                            "entry_price": entry_price,
                            "close": close,
                            "pnl_pct": round(pnl_pct, 4),
                            "max_loss_pct": max_loss_pct,
                        },
                    )
                )
                continue

            # 2. Trailing stop (thesis: the trend is intact). Ratchets off the
            # high-water mark, so it can fire at a profit — which is why it is
            # THESIS_INVALIDATED, not a loss breach.
            hwm = pos.get("high_water_mark")
            if hwm is not None:
                drawdown = close / float(hwm) - 1
                if drawdown <= -_TRAILING_STOP_DRAWDOWN:
                    exits.append(
                        ExitSnapshot(
                            symbol=symbol,
                            exit_date=signal_day,
                            exit_reason="THESIS_INVALIDATED",
                            exit_context={
                                "rule": "trailing_stop",
                                "high_water_mark": float(hwm),
                                "close": close,
                                "drawdown_from_high": round(drawdown, 4),
                                "trailing_stop_drawdown": _TRAILING_STOP_DRAWDOWN,
                            },
                        )
                    )
                    continue

            # 3. Primary uptrend broken — mirrors the entry screen's uptrend gate
            # (price > 200-day). Below it, the momentum thesis no longer holds.
            sma_200 = row["sma_200"]
            if pd.notna(sma_200) and close < float(sma_200):
                exits.append(
                    ExitSnapshot(
                        symbol=symbol,
                        exit_date=signal_day,
                        exit_reason="THESIS_INVALIDATED",
                        exit_context={
                            "rule": "primary_uptrend_broken",
                            "close": close,
                            "sma_200": float(sma_200),
                        },
                    )
                )
        return exits


if __name__ == "__main__":
    as_of = date.today()

    screener = MomentumEntryScreener()
    candidates = screener.run(get_stock_symbols(), as_of)
    top = sorted(candidates, key=lambda c: c.setup_score, reverse=True)[:5]
    print(f"momentum ({as_of}): {len(candidates)} candidates, top {len(top)}")
    for c in top:
        print(
            f"  {c.symbol:6s} score={c.setup_score:.3f} "
            f"price={c.signal_context['price']} gates={c.passed_gates}"
        )

    if top:
        # Exit-monitor smoke: pretend the top pick was bought at +25% above the
        # current price so the max-loss rule fires, and once at the current
        # price with an inflated high-water mark so the trailing stop fires.
        monitor = MomentumExitMonitor()
        px = top[0].signal_context["price"]
        fake_positions = [
            {"symbol": top[0].symbol, "entry_price": px * 1.25},
            {"symbol": top[0].symbol, "entry_price": px, "high_water_mark": px * 1.30},
        ]
        for snap in monitor.run(fake_positions, as_of):
            print(f"  exit {snap.symbol}: {snap.exit_reason} {snap.exit_context}")
