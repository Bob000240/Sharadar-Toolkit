import pandas as pd
from dataclasses import dataclass

import database.market.insider_repo as insider_repo

# Only transaction-code P purchases are treated as positive evidence.
# Grants (A), option exercises (M/X), and tax withholding (F) are plan-based.
_BUY_CODES = {"P"}  # Open-market or private purchase
_SELL_CODES = {"S"}  # Open market or private sale
ROUTINE_PATTERN_YEARS = 3


def _unique_owner_count(transactions: pd.DataFrame) -> int:
    owners = (
        transactions["ownername"]
        .fillna("")
        .str.strip()
        .str.casefold()
        .replace("", pd.NA)
    )
    return int(owners.nunique())


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
            "routine" if expected_periods.issubset(prior_periods) else "opportunistic"
        )

    return pd.Series(classifications).reindex(purchases.index)


@dataclass
class InsiderSnapshot:
    ticker: str
    signal_day: pd.Timestamp

    # Open market buys (filingdate-based, point-in-time)
    buy_count_30d: int
    buy_count_90d: int
    buy_value_30d: float  # USD
    buy_value_90d: float

    # Open market sells
    sell_count_30d: int
    sell_count_90d: int
    sell_value_30d: float
    sell_value_90d: float

    # Cluster metrics (distinct insiders, last 30d)
    unique_buyers_30d: int
    unique_sellers_30d: int
    unique_opportunistic_buyers_30d: int

    # Seniority of buyers (last 30d)
    officer_buys_30d: int
    director_buys_30d: int
    opportunistic_officer_buys_30d: int
    opportunistic_director_buys_30d: int

    # Purchase classification and conviction evidence (last 30d)
    opportunistic_buy_count_30d: int
    routine_buy_count_30d: int
    unclassified_buy_count_30d: int
    opportunistic_buy_value_30d: float
    max_purchase_fraction_of_post_holdings_30d: float

    # Net sentiment over 90d: (buys - sells) / (buys + sells), NaN if no activity
    net_buy_ratio_90d: float

    days_since_last_buy: int | None
    days_since_last_sell: int | None

    def purchase_metrics(self, marketcap: float) -> dict[str, float]:
        normalized_value = float("nan")
        if pd.notna(marketcap) and marketcap > 0:
            normalized_value = self.opportunistic_buy_value_30d / marketcap
        return {
            "opportunistic_buy_value_30d": self.opportunistic_buy_value_30d,
            "opportunistic_value_to_marketcap": normalized_value,
            "max_purchase_fraction_of_post_holdings": (
                self.max_purchase_fraction_of_post_holdings_30d
            ),
        }

    def risk_flags(self) -> dict[str, bool]:
        return {
            "heavy_selling_30d": self.sell_count_30d >= 3,
            "cluster_sell_30d": self.unique_sellers_30d >= 2,
            "large_sell_30d": self.sell_value_30d >= 500_000,
            "only_selling_30d": self.sell_count_30d > 0 and self.buy_count_30d == 0,
        }


class InsiderModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        tickers: list[str],
        lookback_days: int = 90,
    ):
        self.signal_day = signal_day
        self.tickers = tickers
        self.lookback_days = lookback_days
        self.data: dict[str, pd.DataFrame] = {}
        self.load_data()

    def load_data(self) -> None:
        start = self.signal_day - pd.DateOffset(years=ROUTINE_PATTERN_YEARS + 1)
        df = insider_repo.get(
            tickers=self.tickers,
            start_date=str(start.date()),
            end_date=str(self.signal_day.date()),
        )
        if df.empty:
            return
        df["filingdate"] = pd.to_datetime(df["filingdate"])
        df["transactiondate"] = pd.to_datetime(df["transactiondate"])
        df = df[df["transactioncode"].isin(_BUY_CODES | _SELL_CODES)]
        for tkr, grp in df.groupby("ticker"):
            self.data[tkr] = grp.reset_index(drop=True)

    def _agg(self, tkr: str) -> dict:
        grp = self.data.get(tkr)
        cutoff_30d = self.signal_day - pd.Timedelta(days=30)
        cutoff_90d = self.signal_day - pd.Timedelta(days=self.lookback_days)

        _empty = dict(
            buy_count_30d=0,
            buy_count_90d=0,
            buy_value_30d=0.0,
            buy_value_90d=0.0,
            sell_count_30d=0,
            sell_count_90d=0,
            sell_value_30d=0.0,
            sell_value_90d=0.0,
            unique_buyers_30d=0,
            unique_sellers_30d=0,
            unique_opportunistic_buyers_30d=0,
            officer_buys_30d=0,
            director_buys_30d=0,
            opportunistic_officer_buys_30d=0,
            opportunistic_director_buys_30d=0,
            opportunistic_buy_count_30d=0,
            routine_buy_count_30d=0,
            unclassified_buy_count_30d=0,
            opportunistic_buy_value_30d=0.0,
            max_purchase_fraction_of_post_holdings_30d=float("nan"),
            net_buy_ratio_90d=float("nan"),
            days_since_last_buy=None,
            days_since_last_sell=None,
        )
        if grp is None or grp.empty:
            return _empty

        grp = grp.copy()
        grp["filingdate"] = pd.to_datetime(grp["filingdate"])
        grp["transactiondate"] = pd.to_datetime(grp["transactiondate"])
        buys = grp[grp["transactioncode"].isin(_BUY_CODES)].copy()
        sells = grp[grp["transactioncode"].isin(_SELL_CODES)].copy()
        buys["_purchase_class"] = _classify_purchases(buys)
        buys_90d = buys[buys["filingdate"] > cutoff_90d]
        sells_90d = sells[sells["filingdate"] > cutoff_90d]
        buys_30d = buys_90d[buys_90d["filingdate"] > cutoff_30d]
        sells_30d = sells_90d[sells_90d["filingdate"] > cutoff_30d]
        opportunistic_buys_30d = buys_30d[
            buys_30d["_purchase_class"] == "opportunistic"
        ]
        routine_buys_30d = buys_30d[buys_30d["_purchase_class"] == "routine"]
        unclassified_buys_30d = buys_30d[buys_30d["_purchase_class"] == "unclassified"]

        total = len(buys_90d) + len(sells_90d)
        net_buy_ratio = (
            (len(buys_90d) - len(sells_90d)) / total if total > 0 else float("nan")
        )

        transaction_shares = pd.to_numeric(
            opportunistic_buys_30d["transactionshares"], errors="coerce"
        ).abs()
        post_holdings = pd.to_numeric(
            opportunistic_buys_30d["sharesownedfollowingtransaction"],
            errors="coerce",
        )
        purchase_fraction = transaction_shares / post_holdings.where(post_holdings > 0)
        purchase_fraction = purchase_fraction.where(purchase_fraction.between(0, 1))

        def days_since(df_sub: pd.DataFrame) -> int | None:
            if df_sub.empty:
                return None
            return int((self.signal_day - df_sub["filingdate"].max()).days)

        return dict(
            buy_count_30d=len(buys_30d),
            buy_count_90d=len(buys_90d),
            buy_value_30d=float(buys_30d["transactionvalue"].abs().fillna(0).sum()),
            buy_value_90d=float(buys_90d["transactionvalue"].abs().fillna(0).sum()),
            sell_count_30d=len(sells_30d),
            sell_count_90d=len(sells_90d),
            sell_value_30d=float(sells_30d["transactionvalue"].abs().fillna(0).sum()),
            sell_value_90d=float(sells_90d["transactionvalue"].abs().fillna(0).sum()),
            unique_buyers_30d=_unique_owner_count(buys_30d),
            unique_sellers_30d=_unique_owner_count(sells_30d),
            unique_opportunistic_buyers_30d=_unique_owner_count(opportunistic_buys_30d),
            officer_buys_30d=int((buys_30d["isofficer"] == "Y").sum()),
            director_buys_30d=int((buys_30d["isdirector"] == "Y").sum()),
            opportunistic_officer_buys_30d=int(
                (opportunistic_buys_30d["isofficer"] == "Y").sum()
            ),
            opportunistic_director_buys_30d=int(
                (opportunistic_buys_30d["isdirector"] == "Y").sum()
            ),
            opportunistic_buy_count_30d=len(opportunistic_buys_30d),
            routine_buy_count_30d=len(routine_buys_30d),
            unclassified_buy_count_30d=len(unclassified_buys_30d),
            opportunistic_buy_value_30d=float(
                opportunistic_buys_30d["transactionvalue"].abs().fillna(0).sum()
            ),
            max_purchase_fraction_of_post_holdings_30d=float(purchase_fraction.max()),
            net_buy_ratio_90d=net_buy_ratio,
            days_since_last_buy=days_since(buys_90d),
            days_since_last_sell=days_since(sells_90d),
        )

    def build_snapshot(self, ticker: str) -> InsiderSnapshot:
        return InsiderSnapshot(
            ticker=ticker, signal_day=self.signal_day, **self._agg(ticker)
        )


