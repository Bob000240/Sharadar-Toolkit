"""
Strategy base: the deterministic spine shared by every strategy.

A concrete strategy declares NAME + PROFILE (its risk mandate) and implements
screen(). The base owns everything common: profile self-seeding, universe
resolution, macro overlay, per-name price/levels lookup, risk-menu construction,
and candidate-packet assembly + persistence. See PROJECT_IMPLEMENTATION.md.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from data.signals.sig_macro import MacroModel, MacroOverlay
import database.market.indicators_repo as indicators_repo
import database.operational.prefilter_profiles_repository as profiles_repo
import database.operational.screened_candidates_repository as candidates_repo
import decision_layer.det_layer.risk_menu as risk_menu


DEFAULT_CONVICTION = {"HIGH_CONVICTION": 1.0, "CONVICTION": 0.6, "LOW_CONVICTION": 0.3}

_REGIME_SCORE = {"supportive": 0.75, "mixed": 0.5, "hostile": 0.25}

_PROFILE_KEYS = (
    "name", "version", "description", "is_active", "universe",
    "default_holding_days", "max_position_pct", "max_loss_pct",
    "allowed_stop_ids", "allowed_target_ids", "allowed_timeline_ids",
    "default_stop_id", "default_target_id", "default_timeline_id",
    "conviction_size_multipliers",
    "backtest_win_rate", "backtest_expectancy", "backtest_sharpe",
    "backtest_start_date", "backtest_end_date",
    "wf_win_rate", "wf_expectancy", "wf_sharpe", "wf_start_date", "wf_end_date",
)


@dataclass
class ScreenResult:
    """One ticker that passed a strategy's gates, with everything the base needs
    to price it and assemble a candidate packet."""

    symbol: str
    setup_score: float
    passed_gates: list[str]
    risk_flags: list[str]
    entry_price: float
    atr: float | None
    levels: dict = field(default_factory=dict)
    signal_context: dict = field(default_factory=dict)


def _full_profile(profile: dict) -> dict:
    row = {key: None for key in _PROFILE_KEYS}
    row["version"] = "1.0"
    row["is_active"] = True
    row["conviction_size_multipliers"] = DEFAULT_CONVICTION
    row.update(profile)
    return row


class Strategy(ABC):
    # Subclasses set these.
    NAME: str = ""
    PROFILE: dict = {}

    def __init__(self) -> None:
        if not self.NAME or not self.PROFILE:
            raise ValueError(f"{type(self).__name__} must define NAME and PROFILE")
        # Self-seed the profile (idempotent upsert) so the strategy is runnable
        # standalone, then load it back to capture profile_id.
        row = _full_profile({**self.PROFILE, "name": self.NAME})
        profiles_repo.upsert_profile(row)
        self.profile = profiles_repo.get_profile(self.NAME, row["version"])

    # ── Shared machinery ──────────────────────────────────────────────────

    def _resolve_universe(self, tickers: list[str] | None) -> list[str]:
        if tickers is not None:
            return tickers
        from set_up.config import get_stock_symbols

        return get_stock_symbols()

    def _rank_key(self, packet: dict):
        """Ranking key for top_n selection (higher = better). Default is the
        setup_score; a strategy whose score saturates can override to add a
        tiebreaker."""
        return packet["setup_score"]

    def _macro_context(self, signal_day: date) -> tuple[MacroOverlay, float]:
        overlay = MacroModel(pd.Timestamp(signal_day)).build_snapshot().overlay()
        score = _REGIME_SCORE.get(overlay.regime, 0.5)
        if overlay.hard_veto:
            score = min(score, 0.10)
        return overlay, score

    def _price_levels(self, signal_day: date, tickers: list[str]) -> pd.DataFrame:
        """Latest close / ATR / 50DMA per ticker as of signal_day (point-in-time)."""
        df = indicators_repo.get_latest(tickers, pd.Timestamp(signal_day))
        if df.empty:
            return pd.DataFrame(columns=["close", "atr_14", "sma_50"])
        return df.set_index("ticker")[["close", "atr_14", "sma_50"]]

    def _packet(
        self,
        signal_day: date,
        result: ScreenResult,
        menus: dict,
        overlay: MacroOverlay,
        macro_score: float,
    ) -> dict:
        p = self.profile
        stop, target, timeline = (
            menus["default_stop"], menus["default_target"], menus["default_timeline"]
        )
        return {
            "symbol": result.symbol,
            "decision_date": pd.Timestamp(signal_day).date(),
            "profile_id": p["profile_id"],
            "setup_score": round(float(result.setup_score), 4),
            "passed_gates": result.passed_gates,
            "risk_flags": result.risk_flags,
            "stop_menu": menus["stop_menu"],
            "target_menu": menus["target_menu"],
            "timeline_menu": menus["timeline_menu"],
            "default_stop_id": stop["id"] if stop else None,
            "default_target_id": target["id"] if target else None,
            "default_timeline_id": timeline["id"] if timeline else None,
            "default_holding_days": timeline["days"] if timeline else None,
            "max_position_pct": p["max_position_pct"],
            "max_loss_pct": p["max_loss_pct"],
            "entry_price": round(float(result.entry_price), 4),
            "market_regime": overlay.regime,
            "macro_score": round(float(macro_score), 4),
            "backtest_win_rate": p.get("backtest_win_rate"),
            "backtest_expectancy": p.get("backtest_expectancy"),
            "backtest_sharpe": p.get("backtest_sharpe"),
            "signal_context": {**result.signal_context, "macro_overlay": overlay.to_dict()},
            "feature_vector": None,
        }

    def run(
        self,
        signal_day: date,
        tickers: list[str] | None = None,
        persist: bool = True,
        top_n: int | None = None,
    ) -> list[dict]:
        """Orchestrate: resolve universe -> macro -> screen -> price -> emit packets.

        `top_n` selects the highest-ranked packets (by `_rank_key`) for the returned
        shortlist. It is a portfolio-selection convenience, not a screen: the full
        passing set is still persisted for audit; only the returned list is trimmed.
        """
        tickers = self._resolve_universe(tickers)
        overlay, macro_score = self._macro_context(signal_day)
        results = self.screen(signal_day, tickers)

        packets = []
        for result in results:
            menus = risk_menu.build_menus(
                entry=result.entry_price,
                atr=result.atr,
                levels=result.levels,
                allowed_stops=self.profile["allowed_stop_ids"],
                allowed_targets=self.profile["allowed_target_ids"],
                allowed_timelines=self.profile["allowed_timeline_ids"],
                default_stop_id=self.profile["default_stop_id"],
                default_target_id=self.profile["default_target_id"],
                default_timeline_id=self.profile["default_timeline_id"],
            )
            # A name with no priceable stop+target can't be a tradeable candidate.
            if not menus["stop_menu"] or not menus["target_menu"]:
                continue
            packet = self._packet(signal_day, result, menus, overlay, macro_score)
            if persist:
                packet["candidate_id"] = candidates_repo.insert_candidate(packet)
            packets.append(packet)

        if top_n is not None:
            packets = sorted(packets, key=self._rank_key, reverse=True)[:top_n]
        return packets

    # ── Strategy-owned ────────────────────────────────────────────────────

    @abstractmethod
    def screen(self, signal_day: date, tickers: list[str]) -> list[ScreenResult]:
        """Apply this strategy's deterministic gates and scoring to the universe."""
        ...
