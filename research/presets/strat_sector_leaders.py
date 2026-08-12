from dataclasses import dataclass
from datetime import date

import pandas as pd

import database.state.strategy_profiles_repository as profiles_repo
from data.signals.sig_events import (
    EventSignals,
    BANKRUPTCY_CODE,
    DELISTING_CODE,
    LATE_FILING_CODE,
    MATERIAL_IMPAIRMENT_CODE,
    RESTATEMENT_CODE,
)
from data.signals.sig_fundamentals import FundamentalSignals
from data.signals.sig_technical import TechnicalSignals
from research.filters import Filters, attach_signals
from research.universe import Universe

NAME = "sector_leaders"
DESCRIPTION = (
    "Each sector's strongest healthy trend: liquid, profitable, "
    "large-cap names in confirmed uptrends, ranked within sector; "
    "top-5-per-sector menu for the agent."
)


@dataclass
class CandidateSnapshot:
    symbol: str
    entry_date: date
    setup_score: float
    passed_gates: list[str]
    risk_flags: list[str]
    signal_context: dict


@dataclass
class ExitSnapshot:
    symbol: str
    exit_date: date
    exit_reason: str
    exit_context: dict


_GATES = [
    "listed_usd_domestic_common_stock",
    "liquid_min_5m_dollar_volume",
    "traded_within_10d",
    "market_cap_min_10b",
    "positive_net_income",
    "positive_return_60d",
    "positive_return_252d",
    "above_sma_200",
    "rising_trend_slope_60d",
]

_DOMESTIC_COMMON_STOCK_CATEGORIES = (
    "Domestic Common Stock",
    "Domestic Common Stock Primary Class",
)

_MIN_DOLLAR_VOLUME = 5_000_000
_MIN_MARKET_CAP = 10_000_000_000

_ELIGIBILITY_FILTERS = Filters(
    ("currency", "=", "USD"),
    ("category", "in", _DOMESTIC_COMMON_STOCK_CATEGORIES),
    ("dollar_volume_20d_avg", ">=", _MIN_DOLLAR_VOLUME),
    ("marketcap", ">=", _MIN_MARKET_CAP),
    ("netinccmnusd", ">", 0),
    ("return_60d", ">", 0),
    ("return_252d", ">", 0),
    ("pct_from_sma_200", ">", 0),
    ("trend_slope_60d", ">", 0),
)

_EXCLUDING_EVENT_CODES = {
    DELISTING_CODE,
    BANKRUPTCY_CODE,
    RESTATEMENT_CODE,
    LATE_FILING_CODE,
    MATERIAL_IMPAIRMENT_CODE,
}

TECHNICAL_SIGNALS = {
    "vol_adjusted_momentum": 1,
    "r_squared_60d": 1,
    "pct_from_52w_high": 1,
}

VALUE_SIGNALS = {
    "pe": -1,
    "ps": -1,
    "evebitda": -1,
    "fcf_yield": 1,
}

PROFITABILITY_SIGNALS = {
    "gross_profitability": 1,
    "accruals": -1,
    "roic": 1,
}

GROWTH_SIGNALS = {
    "gross_profitability_change_5y": 1,
    "roic_change_5y": 1,
    "cfo_to_assets_change_5y": 1,
}

CAPITAL_DISCIPLINE_SIGNALS = {
    "net_payout_yield": 1,
    "share_dilution_5y": -1,
}

FUNDAMENTAL_SIGNALS = {
    **VALUE_SIGNALS,
    **PROFITABILITY_SIGNALS,
    **GROWTH_SIGNALS,
    **CAPITAL_DISCIPLINE_SIGNALS,
}

SLEEVES = {
    "technical": TECHNICAL_SIGNALS,
    "value": VALUE_SIGNALS,
    "profitability": PROFITABILITY_SIGNALS,
    "growth": GROWTH_SIGNALS,
    "capital_discipline": CAPITAL_DISCIPLINE_SIGNALS,
}

SLEEVE_WEIGHTS = {
    "technical": 0.30,
    "profitability": 0.25,
    "capital_discipline": 0.20,
    "value": 0.15,
    "growth": 0.10,
}

_VALUE_POSITIVE_ONLY = ("pe", "ps", "evebitda")

_MEGA_CAP_THRESHOLD = 200_000_000_000
_TOP_N_PER_SECTOR = 5


class SLEntryScreener:
    """Buy side. Emits the candidate menu: each sector's strongest healthy trends
    among liquid, profitable, already-uptrending names. The structural population
    comes from ``Universe``; this preset owns its strategy-specific filters and
    ranks the survivors within sector.

    Stateless with respect to the signal day — construct once, call run(day) for
    as many days as needed (the registration check is date-independent).
    """

    def __init__(self):
        self.strategy_name = NAME
        self.profile = profiles_repo.get_profile_by_name(NAME)
        if self.profile is None:
            raise RuntimeError(
                f"Strategy {NAME!r} is not registered; run: "
                f"python -m pipeline.main register sector_leaders"
            )
        if not self.profile["active"]:
            raise RuntimeError(f"Strategy {NAME!r} is retired; re-register to run it")
        self.universe = Universe(
            security_types=("common_stock",),
            exchanges=("NYSE", "NASDAQ"),
            recent_trade_days=10,
        )

    @staticmethod
    def _sleeve_score(frame: pd.DataFrame, signals: dict[str, int]) -> pd.Series:
        """Equal-weighted mean of a sleeve's direction-adjusted sector percentiles.
        +1 metrics use `{metric}_sector_pct` as-is; -1 metrics are flipped
        (100 - pct) so higher always means better. skipna: a candidate missing one
        metric is scored on the rest of the sleeve rather than zeroed out."""
        adjusted = {
            metric: (
                frame[f"{metric}_sector_pct"]
                if direction == 1
                else 100 - frame[f"{metric}_sector_pct"]
            )
            for metric, direction in signals.items()
        }
        return pd.DataFrame(adjusted).mean(axis=1, skipna=True)

    def rank(self, candidates: pd.DataFrame) -> pd.DataFrame:
        """Attach the five sleeve scores and the blended setup_score, then keep the
        top N per sector. Weights are renormalized per row over whichever sleeves
        have data, so a candidate missing an entire sleeve (e.g. no 5-year history)
        is scored on the rest rather than penalized to zero."""
        ranked = candidates.copy()
        sleeve_scores = pd.DataFrame(
            {
                name: self._sleeve_score(ranked, signals)
                for name, signals in SLEEVES.items()
            }
        )
        for name in sleeve_scores.columns:
            ranked[f"{name}_score"] = sleeve_scores[name]

        weights = pd.Series(SLEEVE_WEIGHTS)
        available = sleeve_scores.notna().mul(weights, axis=1).sum(axis=1)
        ranked["setup_score"] = (
            sleeve_scores.mul(weights, axis=1).sum(axis=1, min_count=1) / available
        )

        return (
            ranked.dropna(subset=["setup_score"])
            .sort_values("setup_score", ascending=False)
            .groupby("sector", group_keys=False)
            .head(_TOP_N_PER_SECTOR)
        )

    def risk(self, row: pd.Series) -> list[str]:
        """Non-disqualifying context flags for one candidate. These inform the
        agent; they never remove a name from the menu. Risks the eligibility gates
        already exclude (illiquidity, deep drawdowns from a broken trend) are
        intentionally absent — they can't fire on an eligible name."""
        rules = {
            "overbought": row["rsi_14"] > 70,
            "volatile_base": row["consolidation_tightness"] > 1.5,
            "high_volatility": row["volatility_20"] > 0.04,
            "atr_elevated": row["atr_pct"] > 0.04,
            "mega_cap_crowding": row["marketcap"] >= _MEGA_CAP_THRESHOLD,
        }
        flags = [name for name, triggered in rules.items() if triggered]

        days_since_earnings = row.get("days_since_last_earnings")
        if pd.notna(days_since_earnings):
            if days_since_earnings <= 3:
                flags.append("just_reported")
            elif days_since_earnings <= 7:
                flags.append("post_earnings")
        return flags

    def to_snapshot(self, row: pd.Series, signal_day: date) -> CandidateSnapshot:
        """Freeze one ranked row into the packet handed to the agent."""

        def number(key: str, digits: int = 2):
            value = row.get(key)
            return round(float(value), digits) if pd.notna(value) else None

        days_since_earnings = row.get("days_since_last_earnings")
        return CandidateSnapshot(
            symbol=row["ticker"],
            entry_date=signal_day,
            setup_score=round(float(row["setup_score"]), 2),
            passed_gates=list(_GATES),
            risk_flags=self.risk(row),
            signal_context={
                "sector": row["sector"],
                "price": number("close", 4),
                "marketcap": number("marketcap", 0),
                "technical_score": number("technical_score"),
                "value_score": number("value_score"),
                "profitability_score": number("profitability_score"),
                "growth_score": number("growth_score"),
                "capital_discipline_score": number("capital_discipline_score"),
                "days_since_last_earnings": (
                    int(days_since_earnings) if pd.notna(days_since_earnings) else None
                ),
            },
        )

    def run(self, signal_day: date) -> list[CandidateSnapshot]:
        eligible = self.universe.run(signal_day)
        if eligible.empty:
            return []

        eligible = attach_signals(eligible, signal_day)
        eligible = _ELIGIBILITY_FILTERS.apply(eligible)
        if eligible.empty:
            return []

        # attach_signals already produced the raw and derived facts needed for
        # both the eligibility gates and ranking. Reuse that frame rather than
        # querying the signal repositories a second time.
        eligible = eligible.set_index("ticker", drop=False)
        eligible = FundamentalSignals.attach_sectors(eligible)
        eligible = FundamentalSignals.attach_sector_ranks(
            eligible,
            FUNDAMENTAL_SIGNALS,
            positive_only=_VALUE_POSITIVE_ONLY,
        )
        eligible = TechnicalSignals.attach_sector_ranks(
            eligible,
            TECHNICAL_SIGNALS,
        )

        tickers = eligible["ticker"].tolist()
        events = EventSignals.attach_event_facts(tickers, signal_day)
        eligible = eligible.join(events, how="left")
        excluded = eligible["recent_event_codes"].apply(
            lambda codes: (
                any(code in _EXCLUDING_EVENT_CODES for code in codes)
                if isinstance(codes, list)
                else False
            )
        )
        eligible = eligible[~excluded]
        if eligible.empty:
            return []

        menu = self.rank(eligible)
        return [self.to_snapshot(row, signal_day) for _, row in menu.iterrows()]


class SLExitMonitor:
    def __init__(self):
        self.strategy_name = NAME
        self.profile = profiles_repo.get_profile_by_name(NAME)
        if self.profile is None:
            raise RuntimeError(
                f"Strategy {NAME!r} is not registered; run: "
                f"python -m pipeline.main register sector_leaders"
            )

    def run(self, positions: list[dict], signal_day: date) -> list[ExitSnapshot]:
        if not positions:
            return []
        raise NotImplementedError(
            "Exit rules are not implemented: the universal max-loss floor, the "
            "trailing stop from the high-water mark, and the primary-uptrend break. "
            "See PROJECT_IMPLEMENTATION.md § Exit pipeline."
        )


if __name__ == "__main__":
    as_of = date.today()

    screener = SLEntryScreener()
    candidates = screener.run(as_of)
    print(
        f"sector_leaders ({as_of}): {len(candidates)} candidates "
        f"(up to {_TOP_N_PER_SECTOR} per sector)"
    )

    by_sector: dict[str, list[CandidateSnapshot]] = {}
    for candidate in candidates:
        by_sector.setdefault(candidate.signal_context["sector"], []).append(candidate)

    for sector in sorted(by_sector):
        print(f"\n{sector}")
        for candidate in sorted(
            by_sector[sector], key=lambda c: c.setup_score, reverse=True
        ):
            context = candidate.signal_context
            print(
                f"  {candidate.symbol:6s} score={candidate.setup_score:5.2f}"
                f"  tech={context['technical_score']}"
                f"  value={context['value_score']}"
                f"  profit={context['profitability_score']}"
                f"  flags={candidate.risk_flags}"
            )
