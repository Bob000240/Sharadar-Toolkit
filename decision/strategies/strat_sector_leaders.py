from dataclasses import dataclass
from datetime import date

import pandas as pd

from data.signals.sig_fundamentals import FundamentalSignals
from data.signals.sig_technical import TechnicalSignals
import database.state.strategy_profiles_repository as profiles_repo

NAME = "sector_leaders"
DESCRIPTION = (
    "Each sector's strongest healthy trend: liquid, profitable, "
    "mid-cap+ names in confirmed uptrends, ranked within sector; "
    "top-5-per-sector menu for the agent."
)

@dataclass
class CandidateSnapshot:
    symbol: str
    entry_date: date  # the signal_day this candidate was screened
    setup_score: float
    passed_gates: list[str]
    risk_flags: list[str]
    signal_context: dict  # the numbers behind the pass


@dataclass
class ExitSnapshot:
    symbol: str
    exit_date: date  # the signal_day the exit condition fired
    exit_reason: str  # MAXIMUM_LOSS_BREACH / THESIS_INVALIDATED / CONCERNING_EVENTS
    exit_context: dict  # which rule fired, values, agent citation


# ── calibration ──────────────────────────────────────────────────────────────

# Prefilter:
_MIN_DOLLAR_VOLUME = 5_000_000
_MIN_MARKET_CAP = 1_000_000_000
_MIN_RETURN_252D = 0
_MIN_RETURN_60D = 0

# Event-code interpretation belongs to the strategy, not the signal layer.
_EXCLUDING_EVENT_CODES = {
    "31": "delisting_risk",
    "13": "bankruptcy",
    "42": "restatement",
    "36": "late_filing",
    "26": "material_impairment",
}

# Ranking signals per sleeve: {signal: direction}, where +1 = higher is better
# and -1 = lower is better (the flip the strategy applies before blending).
TECHNICAL_SIGNALS = {
    "vol_adjusted_momentum": 1,
    "r_squared_60d": 1,
    "pct_from_52w_high": 1,
}  # weight 1/3 for each

VALUE_SIGNALS = {
    "pe": -1,
    "ps": -1,
    "evebitda": -1,
    "fcf_yield": 1,
}  # weight 1/4 for each

PROFITABILITY_SIGNALS = {
    "gross_profitability": 1,
    "accruals": -1,
    "roic": 1,
}  # weight 1/3 for each

GROWTH_SIGNALS = {
    "gross_profitability_change_5y": 1,
    "roic_change_5y": 1,
    "cfo_to_assets_change_5y": 1,
}  # weight 1/3 for each

CAPITAL_DISCIPLINE_SIGNALS = {
    "net_payout_yield": 1,
    "share_dilution_5y": -1,
}  # weight 1/2 for each

# All fundamental-sleeve signals, merged: the one list FundamentalSignals ranks
# against. Technical signals are ranked separately (different frame/source).
FUNDAMENTAL_SIGNALS = {
    **VALUE_SIGNALS,
    **PROFITABILITY_SIGNALS,
    **GROWTH_SIGNALS,
    **CAPITAL_DISCIPLINE_SIGNALS,
}

# Valuation multiples where a non-positive value is UNDEFINED (a loss-maker's
# PE), not merely extreme — masked out of the rank rather than ranked "cheapest".
_VALUE_POSITIVE_ONLY = ("pe", "ps", "evebitda")



class SLEntryScreener:
    """Buy side. Emits the candidate menu: each sector's strongest healthy trends
    among liquid, profitable, already-uptrending names (enforced upstream in
    _prefilter). Screen = light price-state gates, then rank within sector."""

    def __init__(self):
        self.strategy_name = NAME
        self.profile = profiles_repo.get_profile_by_name(NAME)
        if self.profile is None:
            raise RuntimeError(
                f"Strategy {NAME!r} is not registered; run: "
                f"python -m pipeline.main register decision.strategies.strat_sector_leaders"
            )
        if not self.profile["active"]:
            raise RuntimeError(f"Strategy {NAME!r} is retired; re-register to run it")

    def _prefilter(self, signal_day: date) -> pd.DataFrame:
        """Eligible universe, point-in-time as of signal_day: listing + liquidity
        + recency (equity_prices) + PIT cap + profitability (fundamentals ART) +
        PIT 60d/252d return floors and primary uptrend (close > sma_200), both
        from technical features. Events exclusion stays in run() after EventSignals
        parses the raw eventcodes."""
        from sqlalchemy import text
        from database.db_connection import get_connection

        as_of = pd.Timestamp(signal_day).date().isoformat()
        query = text("""
            SELECT t.ticker, funda.marketcap
            FROM tickers AS t
            JOIN LATERAL (
                SELECT
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY prices.dollar_volume
                    ) AS median_dollar_volume_20d,
                    MAX(prices.date) AS last_traded
                FROM (
                    SELECT ep.date, ep.close * ep.volume AS dollar_volume
                    FROM equity_prices AS ep
                    WHERE ep.ticker = t.ticker
                      AND ep.date <= :as_of
                      AND ep.close > 0
                      AND ep.volume >= 0
                    ORDER BY ep.date DESC
                    LIMIT 20
                ) AS prices
                HAVING COUNT(*) >= 15
            ) AS liquidity ON TRUE
            JOIN LATERAL (
                SELECT f.marketcap, f.netinccmnusd
                FROM fundamentals AS f
                WHERE f.ticker = t.ticker
                  AND f.dimension = 'ART'
                  AND f.datekey <= CAST(:as_of AS date)
                ORDER BY f.datekey DESC
                LIMIT 1
            ) AS funda ON TRUE
            JOIN LATERAL (
                SELECT tf.close, tf.sma_200, tf.return_60d, tf.return_252d
                FROM technical_features AS tf
                WHERE tf.ticker = t.ticker
                  AND tf.date <= CAST(:as_of AS date)
                ORDER BY tf.date DESC
                LIMIT 1
            ) AS technical ON TRUE
            WHERE t.table_code = 'SEP'
              AND t.currency = 'USD'
              AND t.exchange IN ('NYSE', 'NASDAQ')
              AND t.category LIKE 'Domestic Common Stock%'
              AND t.category NOT LIKE '%Secondary%'
              AND liquidity.median_dollar_volume_20d >= :min_dollar_volume
              AND liquidity.last_traded >= CAST(:as_of AS date) - 10
              AND funda.marketcap >= :min_market_cap
              AND funda.netinccmnusd > 0
              AND technical.return_60d > :min_return_60d
              AND technical.return_252d > :min_return_252d
              AND technical.close > technical.sma_200
            ORDER BY t.ticker
        """)
        return pd.read_sql_query(
            query,
            get_connection(),
            params={
                "as_of": as_of,
                "min_dollar_volume": _MIN_DOLLAR_VOLUME,
                "min_market_cap": _MIN_MARKET_CAP,
                "min_return_60d": _MIN_RETURN_60D,
                "min_return_252d": _MIN_RETURN_252D,
            },
        )
    def _screen():
        pass

    def run(self, signal_day: date) -> list[CandidateSnapshot]:
        eligible = self._prefilter(signal_day)
        if eligible.empty:
            return []
        tickers = eligible["ticker"].tolist()

        fundamentals = FundamentalSignals.get_signals(tickers, signal_day)
        fundamentals = FundamentalSignals.attach_sectors(fundamentals)
        fundamentals = FundamentalSignals.attach_history_features(fundamentals, signal_day)
        fundamentals = FundamentalSignals.attach_ratios(fundamentals)
        fundamentals = FundamentalSignals.attach_growth(fundamentals, signal_day)
        fundamentals = FundamentalSignals.attach_sector_ranks(
            fundamentals, FUNDAMENTAL_SIGNALS, positive_only=_VALUE_POSITIVE_ONLY
        )
        # eligible already carries the PIT marketcap used by _prefilter; drop the
        # raw ART marketcap so the join below doesn't collide on the column name.
        fundamentals = fundamentals.drop(columns=["marketcap"])
        eligible = eligible.join(fundamentals, on="ticker", how="left")

        technicals = TechnicalSignals.get_signals(tickers, signal_day)
        technicals = TechnicalSignals.attach_sectors(technicals)
        technicals = TechnicalSignals.attach_sector_ranks(technicals, TECHNICAL_SIGNALS)
        # sector is already merged in from the fundamentals join above.
        technicals = technicals.drop(columns=["sector"])
        eligible = eligible.join(technicals, on="ticker", how="left")

        return eligible

class SLExitMonitor:
    def __init__(self):
        self.strategy_name = NAME
        self.profile = profiles_repo.get_profile_by_name(NAME)
        if self.profile is None:
            raise RuntimeError(
                f"Strategy {NAME!r} is not registered; run: "
                f"python -m pipeline.main register decision.strategies.strat_sector_leaders"
            )
        # No `active` check: a retired strategy must still exit its open positions.

    def run(self, positions: list[dict], signal_day: date) -> list[ExitSnapshot]:
        if not positions:
            return []

if __name__ == "__main__":
    as_of = date.today()

    screener = SLEntryScreener()
