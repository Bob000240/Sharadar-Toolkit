"""
sig_insider — insider transaction signals from Sharadar SF2.

Computes signals from Form 4 filings:
  - Net insider buying score (shares purchased vs sold in window)
  - Recent insider activity flag
  - Number of distinct insiders buying / selling

Point-in-time safe: uses filing_date <= decision_date.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
import pandas as pd
import numpy as np
import database.institutional_repository as inst_repo


# Transaction codes that indicate purchases and sales (SEC Form 4 codes)
_BUY_CODES  = {"P"}                      # Open market purchase
_SELL_CODES = {"S"}                      # Open market sale
_AWARD_CODES = {"A", "M", "G", "J"}     # Awards / grants (excluded from buy/sell score)


@dataclass
class InsiderSnapshot:
    ticker: str
    signal_day: pd.Timestamp
    window_days: int

    # Net activity in the window
    net_shares: float | None          # positive = net buying
    net_value: float | None           # USD
    buyers: int                       # distinct insiders who bought
    sellers: int                      # distinct insiders who sold
    buy_transactions: int
    sell_transactions: int

    # Summary signal
    insider_score: float | None       # normalised -1 to +1 (positive = bullish)
    last_buy_days_ago: int | None     # how many days since the most recent purchase
    recent_cluster: bool              # 2+ insiders bought in the last 30 days

class InsiderModel:
    """
    Loads insider transactions for a universe and computes per-ticker signals.

    Usage:
        model = InsiderModel(signal_day, stock_symbols, window_days=90)
        snap  = model.build_snapshot("AAPL")
    """

    def __init__(
        self,
        signal_day: pd.Timestamp,
        stock_symbols: list[str],
        window_days: int = 90,
    ):
        self.signal_day = signal_day
        self.tickers = stock_symbols
        self.window_days = window_days
        self._df: pd.DataFrame = pd.DataFrame()
        self._load()

    def _load(self) -> None:
        end = self.signal_day.date() if hasattr(self.signal_day, "date") else self.signal_day
        start = end - timedelta(days=self.window_days)
        try:
            self._df = inst_repo.get_insider(self.tickers, start, end)
        except Exception:
            self._df = pd.DataFrame()

    def build_snapshot(self, ticker: str) -> InsiderSnapshot:
        signal_date = self.signal_day.date() if hasattr(self.signal_day, "date") else self.signal_day
        start_date  = signal_date - timedelta(days=self.window_days)
        recent_cutoff = signal_date - timedelta(days=30)

        if self._df.empty:
            return self._empty_snapshot(ticker)

        rows = self._df[self._df["ticker"] == ticker].copy() if "ticker" in self._df.columns else pd.DataFrame()

        if rows.empty:
            return self._empty_snapshot(ticker)

        # Ensure date column is datetime
        if "filing_date" in rows.columns:
            rows["filing_date"] = pd.to_datetime(rows["filing_date"]).dt.date

        buys  = rows[rows["transaction_code"].isin(_BUY_CODES)]
        sells = rows[rows["transaction_code"].isin(_SELL_CODES)]

        buy_shares  = buys["transaction_shares"].fillna(0).astype(float).sum()
        sell_shares = sells["transaction_shares"].fillna(0).astype(float).sum()
        buy_value   = buys["transaction_value"].fillna(0).astype(float).sum()
        sell_value  = sells["transaction_value"].fillna(0).astype(float).sum()

        net_shares = buy_shares - sell_shares
        net_value  = buy_value - sell_value

        total_abs = abs(buy_shares) + abs(sell_shares)
        insider_score = (net_shares / total_abs) if total_abs > 0 else None

        # Days since last purchase
        last_buy_days_ago = None
        if not buys.empty and "filing_date" in buys.columns:
            latest_buy = buys["filing_date"].max()
            if latest_buy:
                last_buy_days_ago = (signal_date - latest_buy).days

        # Cluster: 2+ distinct insiders bought in the last 30 days
        recent_buys = buys[buys["filing_date"] >= recent_cutoff] if "filing_date" in buys.columns else pd.DataFrame()
        recent_cluster = (
            recent_buys["owner_name"].nunique() >= 2
            if not recent_buys.empty and "owner_name" in recent_buys.columns
            else False
        )

        return InsiderSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            window_days=self.window_days,
            net_shares=float(net_shares),
            net_value=float(net_value),
            buyers=buys["owner_name"].nunique() if "owner_name" in buys.columns else 0,
            sellers=sells["owner_name"].nunique() if "owner_name" in sells.columns else 0,
            buy_transactions=len(buys),
            sell_transactions=len(sells),
            insider_score=insider_score,
            last_buy_days_ago=last_buy_days_ago,
            recent_cluster=recent_cluster,
        )

    def _empty_snapshot(self, ticker: str) -> InsiderSnapshot:
        return InsiderSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            window_days=self.window_days,
            net_shares=None,
            net_value=None,
            buyers=0,
            sellers=0,
            buy_transactions=0,
            sell_transactions=0,
            insider_score=None,
            last_buy_days_ago=None,
            recent_cluster=False,
        )

    def get_scores(self) -> pd.DataFrame:
        """Return a DataFrame of insider scores for all tickers (useful for screening)."""
        rows = [
            {"ticker": t, "insider_score": self.build_snapshot(t).insider_score}
            for t in self.tickers
        ]
        return pd.DataFrame(rows).set_index("ticker")
