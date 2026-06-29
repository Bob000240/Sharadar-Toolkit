from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from data.signals.sig_macro import MacroModel, MacroSnapshot
import database.operational.prefilter_profiles_repository as profiles_repo


class PreFilter(ABC):

    def __init__(self, profile_name: str, version: str = "1.0") -> None:
        profile = profiles_repo.get_profile(profile_name, version)
        if profile is None:
            raise ValueError(f"No profile found: {profile_name} v{version}")
        self.profile = profile

    # ── Implemented in base ────────────────────────────────────────────────

    def _macro_overlay(self, signal_day: date) -> MacroSnapshot:
        return MacroModel(pd.Timestamp(signal_day)).build_snapshot()


    # ── Abstract: each strategy owns these ────────────────────────────────

    @abstractmethod
    def screen(self, signal_day: date, tickers: list[str]) -> list[dict]:
        """Core selection logic. Returns raw per-ticker signal dicts."""
        ...

    @abstractmethod
    def entry_modes(self, ticker: str, signal_day: date) -> list[str]:
        """Which entry setups this ticker qualifies for (written to passed_gates)."""
        ...

    @abstractmethod
    def exit_conditions(self) -> dict:
        """Risk menu for candidate packets: stops, targets, holding days."""
        ...

    @abstractmethod
    def run(self, signal_day: date, tickers: list[str]) -> list[dict]:
        """Orchestrates screen → entry_modes → exit_conditions → emit packets."""
        ...
