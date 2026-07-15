"""
Strategy base: the deterministic spine shared by every strategy.

A concrete strategy declares NAME and implements screen(). The base owns everything
common: read-only profile lookup, universe resolution, macro overlay, candidate-packet
assembly, and persistence. See PROJECT_IMPLEMENTATION.md.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from data.signals.sig_macro import MacroModel, MacroOverlay
import database.market.indicators_repo as indicators_repo
import database.operational.strategy_profiles_repository as profiles_repo
import database.operational.screened_candidates_repository as candidates_repo

_REGIME_SCORE = {"supportive": 0.75, "mixed": 0.5, "hostile": 0.25}

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


@dataclass
class ExitDecision:
    pass


class UniversalExitPolicy:
    def evaluate(self, position: dict, context: dict) -> ExitDecision:
        raise NotImplementedError


class StrategyExitPolicy:
    def evaluate(self, position: dict, context: dict) -> ExitDecision:
        raise NotImplementedError


class Strategy(ABC):
    # Subclasses set these.
    NAME: str = ""
    EXIT_POLICY: type[StrategyExitPolicy] | None = None

    def __init__(self) -> None:
        if not self.NAME:
            raise ValueError(f"{type(self).__name__} must define NAME")
        self.profile = profiles_repo.get_profile_by_name(self.NAME)
        if self.profile is None:
            raise RuntimeError(
                f"Strategy profile {self.NAME!r} is missing; run set_up.setup_db"
            )

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
        df = indicators_repo.get_latest_rows(tickers, pd.Timestamp(signal_day))
        if df.empty:
            return pd.DataFrame(columns=["close", "atr_14", "sma_50"])
        return df.set_index("ticker")[["close", "atr_14", "sma_50"]]

    def _packet(
        self,
        signal_day: date,
        result: ScreenResult,
        overlay: MacroOverlay,
        macro_score: float,
    ) -> dict:
        p = self.profile
        return {
            "symbol": result.symbol,
            "decision_date": pd.Timestamp(signal_day).date(),
            "profile_id": p["profile_id"],
            "setup_score": round(float(result.setup_score), 4),
            "passed_gates": result.passed_gates,
            "risk_flags": result.risk_flags,
            "max_position_pct": p["max_position_pct"],
            "max_loss_pct": p["max_loss_pct"],
            "entry_price": round(float(result.entry_price), 4),
            "market_regime": overlay.regime,
            "macro_score": round(float(macro_score), 4),
            "signal_context": {
                **result.signal_context,
                "macro_overlay": overlay.to_dict(),
            },
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
            packet = self._packet(signal_day, result, overlay, macro_score)
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
