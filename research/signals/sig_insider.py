"""Point-in-time insider transactions and ticker-level activity facts.

Windows are measured on ``filingdate`` rather than ``transactiondate``: a
purchase is not knowable until disclosed, whatever day it was executed.

The central judgment is routine versus opportunistic. An insider who buys in
the same calendar month every year is following a plan, and that purchase
carries little information; one who breaks the pattern may be acting on
something. ``ROUTINE_PATTERN_YEARS`` sets how many prior years must match.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import database.source.daily_repo as daily_repo
import database.source.insider_repo as insider_repo
from research.signals.sig import Signals


BUY_CODES = {"P"}
SELL_CODES = {"S"}
ROUTINE_PATTERN_YEARS = 3
RECENT_WINDOW_DAYS = 30

ROUTINE = "routine"
OPPORTUNISTIC = "opportunistic"
UNCLASSIFIED = "unclassified"

_COUNTED_FACTS = (
    "buy_count_30d",
    "buy_count_90d",
    "sell_count_30d",
    "sell_count_90d",
    "unique_buyers_30d",
    "unique_sellers_30d",
    "unique_opportunistic_buyers_30d",
    "officer_buys_30d",
    "director_buys_30d",
    "opportunistic_officer_buys_30d",
    "opportunistic_director_buys_30d",
    "opportunistic_buy_count_30d",
    "routine_buy_count_30d",
    "unclassified_buy_count_30d",
)
_SUMMED_FACTS = (
    "buy_value_30d",
    "buy_value_90d",
    "sell_value_30d",
    "sell_value_90d",
    "opportunistic_buy_value_30d",
)
# Undefined rather than zero with nothing filed: no purchase means no fraction,
# no ratio and no elapsed time.
_NULLABLE_FACTS = (
    "max_purchase_fraction_of_post_holdings_30d",
    "net_buy_ratio_90d",
    "days_since_last_buy",
    "days_since_last_sell",
)

ACTIVITY_FACT_COLUMNS = _COUNTED_FACTS + _SUMMED_FACTS + _NULLABLE_FACTS
MARKETCAP_FACT_COLUMN = "opportunistic_value_to_marketcap"

_QUIET_TICKER = {
    **dict.fromkeys(_COUNTED_FACTS, 0),
    **dict.fromkeys(_SUMMED_FACTS, 0.0),
    **dict.fromkeys(_NULLABLE_FACTS, np.nan),
}


class InsiderSignals(Signals):
    """SQL-backed insider transactions with opt-in ticker-level facts.

    ``get_signals`` returns raw transaction rows,
    ``attach_purchase_classification`` labels the purchases among them,
    ``attach_activity_facts`` reduces those to one row per ticker, and
    ``attach_marketcap_normalization`` scales the result against size.
    """

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
        history_years: int = ROUTINE_PATTERN_YEARS + 1,
    ) -> pd.DataFrame:
        """Return raw transactions disclosed on or before the signal day.

        ``history_years`` defaults to one year more than
        ``ROUTINE_PATTERN_YEARS``, the depth needed to tell a recurring
        same-month purchase from a potentially opportunistic one. One row per
        transaction, not one per ticker.
        """
        signal_day = pd.Timestamp(signal_day)
        start = signal_day - pd.DateOffset(years=history_years)
        frame = insider_repo.get(
            tickers=tickers,
            start_date=str(start.date()),
            end_date=str(signal_day.date()),
        )
        if frame.empty:
            return frame.copy()

        frame = frame.copy()
        frame["filingdate"] = pd.to_datetime(frame["filingdate"])
        frame["transactiondate"] = pd.to_datetime(frame["transactiondate"])
        return frame

    @classmethod
    def attach_activity_facts(
        cls,
        frame: pd.DataFrame,
        tickers: list[str],
        signal_day: pd.Timestamp,
        lookback_days: int = 90,
    ) -> pd.DataFrame:
        """Reduce labelled transactions to one row per requested ticker.

        Expects the frame ``attach_purchase_classification`` returns, since the
        opportunistic counts read the label it adds. Two windows are counted, a
        30-day one and the ``lookback_days`` one. A ticker with nothing filed
        keeps its row with zero counts, because no disclosed purchase is a fact
        rather than missing data.
        """
        signal_day = pd.Timestamp(signal_day)
        grouped = cls._by_ticker(frame)
        rows = [
            {
                "ticker": ticker,
                **cls._ticker_facts(
                    grouped.get(str(ticker)), signal_day, lookback_days
                ),
            }
            for ticker in tickers
        ]
        if not rows:
            return pd.DataFrame(columns=ACTIVITY_FACT_COLUMNS).rename_axis("ticker")
        return pd.DataFrame(rows).set_index("ticker")

    @classmethod
    def attach_purchase_classification(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach a routine or opportunistic label to open-market purchases.

        Only purchase rows are labelled; every other row keeps a null.
        """
        frame = frame.copy()
        frame["purchase_classification"] = pd.Series(
            pd.NA, index=frame.index, dtype="object"
        )
        if frame.empty:
            return frame

        purchases = frame[frame["transactioncode"].isin(BUY_CODES)]
        frame.loc[purchases.index, "purchase_classification"] = cls._classify_purchases(
            purchases
        )
        return frame

    @classmethod
    def attach_marketcap_normalization(
        cls,
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Attach opportunistic purchase value as a fraction of market cap.

        Scales conviction against company size. Priced from SHARADAR/DAILY at the
        signal day, which keeps this source independent of the fundamental chain;
        that market cap arrives in USD millions. Null where it is missing or
        non-positive.
        """
        frame = frame.copy()
        daily = daily_repo.get_latest_rows(
            frame.index.astype(str).tolist(), pd.Timestamp(signal_day)
        )
        marketcaps = (
            pd.Series(dtype=float)
            if daily.empty
            else daily.set_index("ticker")["marketcap"] * 1e6
        )
        aligned = pd.to_numeric(marketcaps.reindex(frame.index), errors="coerce")
        frame[MARKETCAP_FACT_COLUMN] = cls.safe_div(
            frame["opportunistic_buy_value_30d"], aligned.where(aligned > 0)
        )
        return frame

    @staticmethod
    def _by_ticker(transactions: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """Split buy and sell rows into one frame per ticker."""
        if transactions.empty:
            return {}
        traded = transactions[
            transactions["transactioncode"].isin(BUY_CODES | SELL_CODES)
        ]
        return {
            str(ticker): group for ticker, group in traded.groupby("ticker", sort=False)
        }

    @classmethod
    def _classify_purchases(cls, purchases: pd.DataFrame) -> pd.Series:
        """Label each purchase routine, opportunistic, or unclassified.

        Routine means the same insider also bought in that calendar month in each
        of the previous ``ROUTINE_PATTERN_YEARS`` years — a plan rather than a
        decision. A prior purchase counts only if disclosed before this one, so
        the label is decidable from what was knowable at the time. A row with no
        identifiable owner or transaction date is unclassified, not guessed at.
        """
        if purchases.empty:
            return pd.Series(dtype="object", index=purchases.index)

        owner = purchases["ownername"].fillna("").str.strip().str.casefold()
        executed = pd.to_datetime(purchases["transactiondate"])
        filed = pd.to_datetime(purchases["filingdate"])
        identified = owner.ne("") & executed.notna()

        earliest_by_month = (
            pd.DataFrame(
                {
                    "owner": owner[identified],
                    "year": executed[identified].dt.year,
                    "month": executed[identified].dt.month,
                    "filed": filed[identified],
                }
            )
            .groupby(["owner", "year", "month"])["filed"]
            .min()
        )

        repeated = pd.Series(True, index=purchases.index[identified])
        for years_ago in range(1, ROUTINE_PATTERN_YEARS + 1):
            same_month_a_year_back = pd.MultiIndex.from_arrays(
                [
                    owner[identified],
                    executed[identified].dt.year - years_ago,
                    executed[identified].dt.month,
                ]
            )
            disclosed = pd.Series(
                earliest_by_month.reindex(same_month_a_year_back).to_numpy(),
                index=repeated.index,
            )
            repeated &= disclosed.notna() & (disclosed < filed[identified])

        labels = pd.Series(UNCLASSIFIED, index=purchases.index, dtype="object")
        labels[repeated.index] = np.where(repeated, ROUTINE, OPPORTUNISTIC)
        return labels

    @classmethod
    def _ticker_facts(
        cls,
        frame: pd.DataFrame | None,
        signal_day: pd.Timestamp,
        lookback_days: int,
    ) -> dict:
        """Reduce one ticker's transactions to a fact dict.

        Buys and sells are counted separately over both windows, with the
        opportunistic subset broken out by insider role.
        """
        if frame is None or frame.empty:
            return dict(_QUIET_TICKER)

        recent_cutoff = signal_day - pd.Timedelta(days=RECENT_WINDOW_DAYS)
        period_cutoff = signal_day - pd.Timedelta(days=lookback_days)
        buys = frame[frame["transactioncode"].isin(BUY_CODES)]
        sells = frame[frame["transactioncode"].isin(SELL_CODES)]
        buys_period = buys[buys["filingdate"] > period_cutoff]
        sells_period = sells[sells["filingdate"] > period_cutoff]
        buys_recent = buys_period[buys_period["filingdate"] > recent_cutoff]
        sells_recent = sells_period[sells_period["filingdate"] > recent_cutoff]

        label = buys_recent["purchase_classification"]
        opportunistic = buys_recent[label == OPPORTUNISTIC]
        filings = len(buys_period) + len(sells_period)

        return {
            "buy_count_30d": len(buys_recent),
            "buy_count_90d": len(buys_period),
            "buy_value_30d": cls._absolute_value_sum(buys_recent),
            "buy_value_90d": cls._absolute_value_sum(buys_period),
            "sell_count_30d": len(sells_recent),
            "sell_count_90d": len(sells_period),
            "sell_value_30d": cls._absolute_value_sum(sells_recent),
            "sell_value_90d": cls._absolute_value_sum(sells_period),
            "unique_buyers_30d": cls._unique_owner_count(buys_recent),
            "unique_sellers_30d": cls._unique_owner_count(sells_recent),
            "unique_opportunistic_buyers_30d": cls._unique_owner_count(opportunistic),
            "officer_buys_30d": cls._role_count(buys_recent, "isofficer"),
            "director_buys_30d": cls._role_count(buys_recent, "isdirector"),
            "opportunistic_officer_buys_30d": cls._role_count(
                opportunistic, "isofficer"
            ),
            "opportunistic_director_buys_30d": cls._role_count(
                opportunistic, "isdirector"
            ),
            "opportunistic_buy_count_30d": len(opportunistic),
            "routine_buy_count_30d": int((label == ROUTINE).sum()),
            "unclassified_buy_count_30d": int((label == UNCLASSIFIED).sum()),
            "opportunistic_buy_value_30d": cls._absolute_value_sum(opportunistic),
            "max_purchase_fraction_of_post_holdings_30d": cls._largest_stake_added(
                opportunistic
            ),
            "net_buy_ratio_90d": (
                (len(buys_period) - len(sells_period)) / filings if filings else np.nan
            ),
            "days_since_last_buy": cls._days_since(buys_period, signal_day),
            "days_since_last_sell": cls._days_since(sells_period, signal_day),
        }

    @staticmethod
    def _unique_owner_count(transactions: pd.DataFrame) -> int:
        """Count distinct insiders, matching names case- and space-insensitively."""
        owners = (
            transactions["ownername"]
            .fillna("")
            .str.strip()
            .str.casefold()
            .replace("", pd.NA)
        )
        return int(owners.nunique())

    @staticmethod
    def _role_count(transactions: pd.DataFrame, role_column: str) -> int:
        """Count transactions whose filer holds ``role_column``."""
        return int((transactions[role_column] == "Y").sum())

    @staticmethod
    def _largest_stake_added(purchases: pd.DataFrame) -> float:
        """Return the largest purchase as a fraction of the buyer's resulting stake.

        Conviction relative to what the insider already owns: a fraction near 1
        means the position was built here rather than topped up. Fractions outside
        0 to 1 are dropped as unreconcilable rather than clipped.
        """
        bought = pd.to_numeric(purchases["transactionshares"], errors="coerce").abs()
        owned_after = pd.to_numeric(
            purchases["sharesownedfollowingtransaction"], errors="coerce"
        )
        fraction = bought / owned_after.where(owned_after > 0)
        return float(fraction.where(fraction.between(0, 1)).max())

    @staticmethod
    def _absolute_value_sum(frame: pd.DataFrame) -> float:
        """Sum transaction values as magnitudes, treating unparsable ones as zero."""
        values = pd.to_numeric(frame["transactionvalue"], errors="coerce")
        return float(values.abs().fillna(0).sum())

    @staticmethod
    def _days_since(frame: pd.DataFrame, signal_day: pd.Timestamp) -> float:
        """Return days since the most recent disclosure, or NaN if there is none."""
        if frame.empty:
            return np.nan
        return float((signal_day - frame["filingdate"].max()).days)
