from dataclasses import dataclass
from datetime import date

import pandas as pd

from data.signals.sig_technicals import TechnicalSignals
from data.signals.sig_events import EventSignals
from set_up.config import cap_bucket
import database.market.indicators_repo as indicators_repo
import database.operational.strategy_profiles_repository as profiles_repo


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

# ── Prefilter:
_MIN_DOLLAR_VOLUME = 5_000_000
_MIN_MARKET_CAP = 1_000_000_000
_MIN_RETURN_252D = 0
_MIN_RETURN_60D = 0

_MEGA_CAP_THRESHOLD = 200_000_000_000

# Trailing stop: drawdown from the position's high-water mark that invalidates
# the trend thesis. 15-20% is the effective band in the stop-loss literature,
# with trailing beating entry-anchored stops; evaluated at run cadence, not
# intraday (prevents over-trading). CALIBRATION within the cited band.
_TRAILING_STOP_DRAWDOWN = 0.20

# Event-code interpretation belongs to the strategy, not the signal layer.
_EXCLUDING_EVENT_CODES = {
    "31": "delisting_risk",
    "13": "bankruptcy",
    "42": "restatement",
    "36": "late_filing",
    "26": "material_impairment",
}


class SLEntryScreener:
    """Buy side. Emits the candidate menu: each sector's strongest healthy trends
    among liquid, profitable, already-uptrending names (enforced upstream in
    _prefilter). Screen = light price-state gates, then rank within sector."""

    def __init__(self):
        self.strategy_name = "sector_leaders"
        self.profile = profiles_repo.get_profile_by_name("sector_leaders")
        if self.profile is None:
            raise RuntimeError(
                "Strategy profile 'sector_leaders' is missing; run set_up.setup_db"
            )

    def _prefilter(self, signal_day: date) -> pd.DataFrame:
        """Eligible universe, point-in-time as of signal_day: listing + liquidity
        + recency (equity_prices) + PIT cap + profitability (fundamentals ART) +
        PIT 60d/252d return floors (indicators). Events exclusion stays in run()
        after EventSignals parses the raw eventcodes."""
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
                SELECT i.return_60d, i.return_252d
                FROM indicators AS i
                WHERE i.ticker = t.ticker
                  AND i.date <= CAST(:as_of AS date)
                ORDER BY i.date DESC
                LIMIT 1
            ) AS ind ON TRUE
            WHERE t.table_code = 'SEP'
              AND t.currency = 'USD'
              AND t.exchange IN ('NYSE', 'NASDAQ')
              AND t.category LIKE 'Domestic Common Stock%'
              AND t.category NOT LIKE '%Secondary%'
              AND liquidity.median_dollar_volume_20d >= :min_dollar_volume
              AND liquidity.last_traded >= CAST(:as_of AS date) - 10
              AND funda.marketcap >= :min_market_cap
              AND funda.netinccmnusd > 0
              AND ind.return_60d > :min_return_60d
              AND ind.return_252d > :min_return_252d
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

    @staticmethod
    def _technical_risk_flags(row: pd.Series) -> list[str]:
        rules = {
            "overbought": row["rsi_14"] > 70,
            "low_liquidity": row["dollar_volume_20d_avg"] < 1_000_000,
            "extended_drawdown": row["pct_from_52w_high"] < -0.30,
            "volatile_base": row["consolidation_tightness"] > 1.5,
            "high_volatility": row["volatility_20"] > 0.04,
            "atr_elevated": row["atr_pct"] > 0.04,
        }
        return [name for name, triggered in rules.items() if triggered]

    def run(self, signal_day: date) -> list[CandidateSnapshot]:
        eligible = self._prefilter(signal_day)
        if eligible.empty:
            return []
        present = eligible["ticker"].tolist()
        ts = pd.Timestamp(signal_day)
        technicals = TechnicalSignals.get_signals(present, ts)
        missing = [ticker for ticker in present if ticker not in technicals.index]
        if missing:
            raise ValueError(f"No indicator data as of {ts.date()} for: {missing}")
        technicals = TechnicalSignals.attach_sectors(technicals)
        technicals = TechnicalSignals.attach_return_percentiles(technicals)
        technicals = TechnicalSignals.attach_sector_features(technicals, ts)
        event_rows = EventSignals.get_signals(present, ts)
        events = EventSignals.attach_event_facts(event_rows, present, ts)
        mcaps = eligible.set_index("ticker")["marketcap"].to_dict()

        candidates: list[CandidateSnapshot] = []
        for ticker in present:
            row = technicals.loc[ticker]
            event_facts = events.loc[ticker]
            recent_codes = set(event_facts["recent_event_codes"])
            excluding_risks = [
                risk_name
                for event_code, risk_name in _EXCLUDING_EVENT_CODES.items()
                if event_code in recent_codes
            ]
            if excluding_risks:
                continue

            mcap = mcaps.get(ticker)
            cap = cap_bucket(mcap)

            uptrend = row["close"] > row["sma_200"]
            trend_confirmed = row["trend_slope_60d"] * row["r_squared_60d"] > 0
            if not (uptrend and trend_confirmed):
                continue

            gates = ["uptrend", "trend_confirmed", f"{cap}_cap"]

            # TODO(sector_leaders): rank within sector by trend quality
            # (vol_adjusted_momentum × r_squared_60d), then keep the top 5 per
            # sector as the menu. Placeholder until the ranking is written.
            setup_score = 0.0

            risk_flags = self._technical_risk_flags(row)
            days_since_earnings = event_facts["days_since_last_earnings"]
            if pd.notna(days_since_earnings):
                if days_since_earnings <= 3:
                    risk_flags.append("just_reported")
                if days_since_earnings <= 7:
                    risk_flags.append("post_earnings")
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
                        "price": round(float(row["close"]), 4),
                        "return_20d_percentile": round(
                            float(row["return_20d_percentile"]), 2
                        ),
                        "return_60d_percentile": round(
                            float(row["return_60d_percentile"]), 2
                        ),
                        "return_252d_percentile": round(
                            float(row["return_252d_percentile"]), 2
                        ),
                        "sector": row["sector"],
                        "sector_rank_20d": (
                            int(row["sector_rank_20d"])
                            if pd.notna(row["sector_rank_20d"])
                            else None
                        ),
                        "sector_score": round(float(row["sector_score"]), 4),
                        "rsi_14": round(float(row["rsi_14"]), 2),
                        "pct_from_52w_high": round(float(row["pct_from_52w_high"]), 4),
                        "trend_slope_60d": round(float(row["trend_slope_60d"]), 6),
                        "r_squared_60d": round(float(row["r_squared_60d"]), 4),
                        "dollar_volume_20d_avg": round(
                            float(row["dollar_volume_20d_avg"]), 0
                        ),
                        "days_since_last_earnings": (
                            int(days_since_earnings)
                            if pd.notna(days_since_earnings)
                            else None
                        ),
                    },
                )
            )
        return candidates


class SLExitMonitor:
    def __init__(self):
        self.strategy_name = "sector_leaders"
        self.profile = profiles_repo.get_profile_by_name("sector_leaders")
        if self.profile is None:
            raise RuntimeError(
                "Strategy profile 'sector_leaders' is missing; run set_up.setup_db"
            )

    def run(self, positions: list[dict], signal_day: date) -> list[ExitSnapshot]:
        if not positions:
            return []
        ts = pd.Timestamp(signal_day)
        symbols = [p["symbol"] for p in positions]
        rows = indicators_repo.get_latest_rows(symbols, ts)
        if rows.empty:
            return []
        rows = rows.set_index("ticker")[["close", "sma_200"]]
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
            # (price > 200-day). Below it, the leader is no longer leading.
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

    screener = SLEntryScreener()
    candidates = screener.run(as_of)
    top = sorted(candidates, key=lambda c: c.setup_score, reverse=True)[:5]
    print(f"sector_leaders ({as_of}): {len(candidates)} candidates, top {len(top)}")
    for c in top:
        print(
            f"  {c.symbol:6s} score={c.setup_score:.3f} "
            f"price={c.signal_context['price']} gates={c.passed_gates}"
        )

    if top:
        # Exit-monitor smoke: pretend the top pick was bought at +25% above the
        # current price so the max-loss rule fires, and once at the current
        # price with an inflated high-water mark so the trailing stop fires.
        monitor = SLExitMonitor()
        px = top[0].signal_context["price"]
        fake_positions = [
            {"symbol": top[0].symbol, "entry_price": px * 1.25},
            {"symbol": top[0].symbol, "entry_price": px, "high_water_mark": px * 1.30},
        ]
        for snap in monitor.run(fake_positions, as_of):
            print(f"  exit {snap.symbol}: {snap.exit_reason} {snap.exit_context}")
