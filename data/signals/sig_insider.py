import pandas as pd
from dataclasses import dataclass

import database.market.insider_repo as insider_repo

# Only open-market transactions carry informational content.
# Grants (A), option exercises (M/X), and tax withholding (F) are plan-based.
_BUY_CODES = {"P"}  # Open market or private purchase
_SELL_CODES = {"S"}  # Open market or private sale


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

    # Seniority of buyers (last 30d)
    officer_buys_30d: int
    director_buys_30d: int

    # Net sentiment over 90d: (buys - sells) / (buys + sells), NaN if no activity
    net_buy_ratio_90d: float

    days_since_last_buy: int | None
    days_since_last_sell: int | None

    def cluster_buying(self) -> dict[str, bool]:
        return {
            "any_buy_30d": self.buy_count_30d > 0,
            "cluster_buy_30d": self.unique_buyers_30d >= 2,
            "cluster_strong": self.unique_buyers_30d >= 3,
            "large_buy_30d": self.buy_value_30d >= 100_000,
        }

    def officer_activity(self) -> dict[str, bool]:
        return {
            "officer_buying": self.officer_buys_30d > 0,
            "director_buying": self.director_buys_30d > 0,
            "senior_cluster": (self.officer_buys_30d + self.director_buys_30d) >= 2,
        }

    def net_sentiment(self) -> dict[str, bool]:
        ratio = self.net_buy_ratio_90d
        return {
            "net_buyer_90d": self.buy_count_90d > self.sell_count_90d,
            "no_selling_30d": self.sell_count_30d == 0,
            "buy_dominant_90d": not pd.isna(ratio) and ratio > 0.5,
        }

    def risk_flags(self) -> dict[str, bool]:
        return {
            "heavy_selling_30d": self.sell_count_30d >= 3,
            "cluster_sell_30d": self.unique_sellers_30d >= 2,
            "large_sell_30d": self.sell_value_30d >= 500_000,
            "only_selling_30d": self.sell_count_30d > 0 and self.buy_count_30d == 0,
        }

    def insider_score(self) -> float:
        score = 0.5
        score += min(self.unique_buyers_30d, 5) * 0.08
        score += 0.05 if self.officer_buys_30d > 0 else 0.0
        score += 0.05 if self.director_buys_30d > 0 else 0.0
        score -= min(self.unique_sellers_30d, 5) * 0.05
        score -= 0.05 if self.sell_count_30d >= 3 else 0.0
        return max(0.0, min(1.0, score))


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
        start = self.signal_day - pd.Timedelta(days=self.lookback_days)
        df = insider_repo.get(
            tickers=self.tickers,
            start_date=str(start.date()),
            end_date=str(self.signal_day.date()),
        )
        if df.empty:
            return
        df["filingdate"] = pd.to_datetime(df["filingdate"])
        df = df[df["transactioncode"].isin(_BUY_CODES | _SELL_CODES)]
        for tkr, grp in df.groupby("ticker"):
            self.data[tkr] = grp.reset_index(drop=True)

    def _agg(self, tkr: str) -> dict:
        grp = self.data.get(tkr)
        cutoff_30d = self.signal_day - pd.Timedelta(days=30)

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
            officer_buys_30d=0,
            director_buys_30d=0,
            net_buy_ratio_90d=float("nan"),
            days_since_last_buy=None,
            days_since_last_sell=None,
        )
        if grp is None or grp.empty:
            return _empty

        buys = grp[grp["transactioncode"].isin(_BUY_CODES)]
        sells = grp[grp["transactioncode"].isin(_SELL_CODES)]
        buys_30d = buys[buys["filingdate"] > cutoff_30d]
        sells_30d = sells[sells["filingdate"] > cutoff_30d]

        total = len(buys) + len(sells)
        net_buy_ratio = (len(buys) - len(sells)) / total if total > 0 else float("nan")

        def days_since(df_sub: pd.DataFrame) -> int | None:
            if df_sub.empty:
                return None
            return int((self.signal_day - df_sub["filingdate"].max()).days)

        return dict(
            buy_count_30d=len(buys_30d),
            buy_count_90d=len(buys),
            buy_value_30d=float(buys_30d["transactionvalue"].abs().fillna(0).sum()),
            buy_value_90d=float(buys["transactionvalue"].abs().fillna(0).sum()),
            sell_count_30d=len(sells_30d),
            sell_count_90d=len(sells),
            sell_value_30d=float(sells_30d["transactionvalue"].abs().fillna(0).sum()),
            sell_value_90d=float(sells["transactionvalue"].abs().fillna(0).sum()),
            unique_buyers_30d=int(buys_30d["ownername"].nunique()),
            unique_sellers_30d=int(sells_30d["ownername"].nunique()),
            officer_buys_30d=int((buys_30d["isofficer"] == "Y").sum()),
            director_buys_30d=int((buys_30d["isdirector"] == "Y").sum()),
            net_buy_ratio_90d=net_buy_ratio,
            days_since_last_buy=days_since(buys),
            days_since_last_sell=days_since(sells),
        )

    def build_snapshot(self, ticker: str) -> InsiderSnapshot:
        return InsiderSnapshot(
            ticker=ticker, signal_day=self.signal_day, **self._agg(ticker)
        )


def print_snapshot_report(snap: InsiderSnapshot) -> None:
    dlb = (
        f"{snap.days_since_last_buy}d ago"
        if snap.days_since_last_buy is not None
        else "none"
    )
    dls = (
        f"{snap.days_since_last_sell}d ago"
        if snap.days_since_last_sell is not None
        else "none"
    )
    print(f"\n=== {snap.ticker} | {snap.signal_day.date()} ===")
    print(
        f"  Buys  30d/90d: {snap.buy_count_30d}/{snap.buy_count_90d}  "
        f"(${snap.buy_value_30d:,.0f} / ${snap.buy_value_90d:,.0f})  last: {dlb}"
    )
    print(
        f"  Sells 30d/90d: {snap.sell_count_30d}/{snap.sell_count_90d}  "
        f"(${snap.sell_value_30d:,.0f} / ${snap.sell_value_90d:,.0f})  last: {dls}"
    )
    print(
        f"  Unique buyers 30d: {snap.unique_buyers_30d}  "
        f"(officers: {snap.officer_buys_30d}, directors: {snap.director_buys_30d})"
    )
    print(
        f"  Net buy ratio 90d: {snap.net_buy_ratio_90d:.2f}"
        if not pd.isna(snap.net_buy_ratio_90d)
        else "  Net buy ratio 90d: n/a"
    )
    print(f"  Insider Score: {snap.insider_score():.3f}")
    print(f"  Cluster Buying: {snap.cluster_buying()}")
    print(f"  Officer Activity: {snap.officer_activity()}")
    print(f"  Net Sentiment:  {snap.net_sentiment()}")
    print(f"  Risk Flags:     {snap.risk_flags()}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2026-06-30")
    tickers = ["AAPL", "MSFT", "GOOGL"]

    model = InsiderModel(signal_day=signal_day, tickers=tickers)
    for tkr in tickers:
        print_snapshot_report(model.build_snapshot(tkr))
