"""Point-in-time insider transaction rows and optional activity facts."""

from __future__ import annotations

import numpy as np
import pandas as pd

import database.source.insider_repo as insider_repo
from research.signals.sig import Signals


BUY_CODES = {"P"}
SELL_CODES = {"S"}
ROUTINE_PATTERN_YEARS = 3

ACTIVITY_FACT_COLUMNS = (
    "buy_count_30d",
    "buy_count_90d",
    "buy_value_30d",
    "buy_value_90d",
    "sell_count_30d",
    "sell_count_90d",
    "sell_value_30d",
    "sell_value_90d",
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
    "opportunistic_buy_value_30d",
    "max_purchase_fraction_of_post_holdings_30d",
    "net_buy_ratio_90d",
    "days_since_last_buy",
    "days_since_last_sell",
)


class InsiderSignals(Signals):
    """SQL-backed insider transactions with opt-in ticker-level facts."""

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
        history_years: int = ROUTINE_PATTERN_YEARS + 1,
    ) -> pd.DataFrame:
        """Return raw transactions known by the signal day.

        The default history includes enough prior years to distinguish recurring
        same-month purchases from potentially opportunistic purchases.
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
    def attach_purchase_classification(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach routine/opportunistic labels to open-market purchase rows."""
        frame = frame.copy()
        frame["purchase_classification"] = pd.Series(
            pd.NA,
            index=frame.index,
            dtype="object",
        )
        if frame.empty:
            return frame

        purchases = frame[frame["transactioncode"].isin(BUY_CODES)]
        frame.loc[purchases.index, "purchase_classification"] = cls._classify_purchases(
            purchases
        )
        return frame

    @classmethod
    def attach_activity_facts(
        cls,
        frame: pd.DataFrame,
        tickers: list[str],
        signal_day: pd.Timestamp,
        lookback_days: int = 90,
    ) -> pd.DataFrame:
        """Aggregate raw transactions into objective recent-activity facts."""
        signal_day = pd.Timestamp(signal_day)
        transactions = cls.attach_purchase_classification(frame)
        if transactions.empty:
            grouped: dict[str, pd.DataFrame] = {}
        else:
            transactions["filingdate"] = pd.to_datetime(transactions["filingdate"])
            transactions["transactiondate"] = pd.to_datetime(
                transactions["transactiondate"]
            )
            transactions = transactions[
                transactions["transactioncode"].isin(BUY_CODES | SELL_CODES)
            ]
            grouped = {
                str(ticker): group
                for ticker, group in transactions.groupby("ticker", sort=False)
            }

        rows = [
            {
                "ticker": ticker,
                **cls._aggregate_ticker(
                    grouped.get(str(ticker)),
                    signal_day,
                    lookback_days,
                ),
            }
            for ticker in tickers
        ]
        if not rows:
            return pd.DataFrame(columns=ACTIVITY_FACT_COLUMNS).rename_axis("ticker")
        return pd.DataFrame(rows).set_index("ticker")

    @classmethod
    def attach_marketcap_normalization(
        cls,
        frame: pd.DataFrame,
        marketcaps: pd.Series,
    ) -> pd.DataFrame:
        """Attach opportunistic purchase value as a fraction of market cap."""
        frame = frame.copy()
        aligned_marketcaps = pd.to_numeric(
            marketcaps.reindex(frame.index),
            errors="coerce",
        )
        frame["opportunistic_value_to_marketcap"] = cls.safe_div(
            frame["opportunistic_buy_value_30d"],
            aligned_marketcaps.where(aligned_marketcaps > 0),
        )
        return frame

    @staticmethod
    def _unique_owner_count(transactions: pd.DataFrame) -> int:
        owners = (
            transactions["ownername"]
            .fillna("")
            .str.strip()
            .str.casefold()
            .replace("", pd.NA)
        )
        return int(owners.nunique())

    @staticmethod
    def _classify_purchases(purchases: pd.DataFrame) -> pd.Series:
        if purchases.empty:
            return pd.Series(dtype="object", index=purchases.index)

        purchases = purchases.copy()
        purchases["filingdate"] = pd.to_datetime(purchases["filingdate"])
        purchases["transactiondate"] = pd.to_datetime(purchases["transactiondate"])
        purchases["_owner_key"] = (
            purchases["ownername"].fillna("").str.strip().str.casefold()
        )
        classifications = {}

        for index, row in purchases.sort_values("filingdate").iterrows():
            transaction_date = row["transactiondate"]
            owner_key = row["_owner_key"]
            if not owner_key or pd.isna(transaction_date):
                classifications[index] = "unclassified"
                continue

            prior = purchases[
                (purchases["_owner_key"] == owner_key)
                & (purchases["filingdate"] < row["filingdate"])
                & (purchases["transactiondate"] < transaction_date)
            ]
            prior_periods = {
                (date.year, date.month) for date in prior["transactiondate"].dropna()
            }
            expected_periods = {
                (transaction_date.year - years_ago, transaction_date.month)
                for years_ago in range(1, ROUTINE_PATTERN_YEARS + 1)
            }
            classifications[index] = (
                "routine"
                if expected_periods.issubset(prior_periods)
                else "opportunistic"
            )

        return pd.Series(classifications).reindex(purchases.index)

    @classmethod
    def _aggregate_ticker(
        cls,
        frame: pd.DataFrame | None,
        signal_day: pd.Timestamp,
        lookback_days: int,
    ) -> dict:
        empty = {
            "buy_count_30d": 0,
            "buy_count_90d": 0,
            "buy_value_30d": 0.0,
            "buy_value_90d": 0.0,
            "sell_count_30d": 0,
            "sell_count_90d": 0,
            "sell_value_30d": 0.0,
            "sell_value_90d": 0.0,
            "unique_buyers_30d": 0,
            "unique_sellers_30d": 0,
            "unique_opportunistic_buyers_30d": 0,
            "officer_buys_30d": 0,
            "director_buys_30d": 0,
            "opportunistic_officer_buys_30d": 0,
            "opportunistic_director_buys_30d": 0,
            "opportunistic_buy_count_30d": 0,
            "routine_buy_count_30d": 0,
            "unclassified_buy_count_30d": 0,
            "opportunistic_buy_value_30d": 0.0,
            "max_purchase_fraction_of_post_holdings_30d": np.nan,
            "net_buy_ratio_90d": np.nan,
            "days_since_last_buy": None,
            "days_since_last_sell": None,
        }
        if frame is None or frame.empty:
            return empty

        cutoff_30d = signal_day - pd.Timedelta(days=30)
        cutoff_period = signal_day - pd.Timedelta(days=lookback_days)
        buys = frame[frame["transactioncode"].isin(BUY_CODES)].copy()
        sells = frame[frame["transactioncode"].isin(SELL_CODES)].copy()
        buys_period = buys[buys["filingdate"] > cutoff_period]
        sells_period = sells[sells["filingdate"] > cutoff_period]
        buys_30d = buys_period[buys_period["filingdate"] > cutoff_30d]
        sells_30d = sells_period[sells_period["filingdate"] > cutoff_30d]
        opportunistic = buys_30d[buys_30d["purchase_classification"] == "opportunistic"]
        routine = buys_30d[buys_30d["purchase_classification"] == "routine"]
        unclassified = buys_30d[buys_30d["purchase_classification"] == "unclassified"]

        transaction_shares = pd.to_numeric(
            opportunistic["transactionshares"],
            errors="coerce",
        ).abs()
        post_holdings = pd.to_numeric(
            opportunistic["sharesownedfollowingtransaction"],
            errors="coerce",
        )
        purchase_fraction = transaction_shares / post_holdings.where(post_holdings > 0)
        purchase_fraction = purchase_fraction.where(purchase_fraction.between(0, 1))

        total_transactions = len(buys_period) + len(sells_period)
        net_buy_ratio = (
            (len(buys_period) - len(sells_period)) / total_transactions
            if total_transactions
            else np.nan
        )

        return {
            "buy_count_30d": len(buys_30d),
            "buy_count_90d": len(buys_period),
            "buy_value_30d": cls._absolute_value_sum(buys_30d),
            "buy_value_90d": cls._absolute_value_sum(buys_period),
            "sell_count_30d": len(sells_30d),
            "sell_count_90d": len(sells_period),
            "sell_value_30d": cls._absolute_value_sum(sells_30d),
            "sell_value_90d": cls._absolute_value_sum(sells_period),
            "unique_buyers_30d": cls._unique_owner_count(buys_30d),
            "unique_sellers_30d": cls._unique_owner_count(sells_30d),
            "unique_opportunistic_buyers_30d": cls._unique_owner_count(opportunistic),
            "officer_buys_30d": int((buys_30d["isofficer"] == "Y").sum()),
            "director_buys_30d": int((buys_30d["isdirector"] == "Y").sum()),
            "opportunistic_officer_buys_30d": int(
                (opportunistic["isofficer"] == "Y").sum()
            ),
            "opportunistic_director_buys_30d": int(
                (opportunistic["isdirector"] == "Y").sum()
            ),
            "opportunistic_buy_count_30d": len(opportunistic),
            "routine_buy_count_30d": len(routine),
            "unclassified_buy_count_30d": len(unclassified),
            "opportunistic_buy_value_30d": cls._absolute_value_sum(opportunistic),
            "max_purchase_fraction_of_post_holdings_30d": float(
                purchase_fraction.max()
            ),
            "net_buy_ratio_90d": net_buy_ratio,
            "days_since_last_buy": cls._days_since(
                buys_period,
                signal_day,
            ),
            "days_since_last_sell": cls._days_since(
                sells_period,
                signal_day,
            ),
        }

    @staticmethod
    def _absolute_value_sum(frame: pd.DataFrame) -> float:
        values = pd.to_numeric(frame["transactionvalue"], errors="coerce")
        return float(values.abs().fillna(0).sum())

    @staticmethod
    def _days_since(
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
    ) -> int | None:
        if frame.empty:
            return None
        return int((signal_day - frame["filingdate"].max()).days)
