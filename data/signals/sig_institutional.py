"""
sig_institutional — institutional ownership signals from Sharadar SF3 / SF3A.

Primary source: institutional_summary (SF3A) — quarterly snapshot of:
  - total shareholders, shareholder count change
  - % of float held by institutions
  - call vs put holder count

Signals:
  - Ownership concentration and trend
  - Smart-money accumulation / distribution
  - Universe percentile ranks

Point-in-time safe: queries use calendar_date <= signal_day.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import numpy as np
import database.institutional_repository as inst_repo


@dataclass
class InstitutionalSnapshot:
    ticker: str
    signal_day: pd.Timestamp
    calendar_date: pd.Timestamp | None   # most recent 13F quarter used

    # Ownership levels
    shareholders: int | None
    shareholders_change: int | None
    shares_held_pct: float | None        # % of float held by institutions
    shares_held_change: float | None     # shares change (positive = accumulation)
    call_holders: int | None
    put_holders: int | None

    # Derived signals
    ownership_trend: float | None        # shareholders_change / shareholders (signed %)
    call_put_ratio: float | None         # call_holders / put_holders (>1 = bullish positioning)
    accumulation_flag: bool              # true if shares_held_change > 0 and shareholders_change > 0

    # Universe percentile ranks
    shares_held_pct_rank: float | None   # higher = more institutionally owned
    ownership_trend_rank: float | None

class InstitutionalModel:
    """
    Loads institutional summary (SF3A) for a universe and computes per-ticker signals.

    Usage:
        model = InstitutionalModel(signal_day, stock_symbols)
        snap  = model.build_snapshot("AAPL")
    """

    def __init__(self, signal_day: pd.Timestamp, stock_symbols: list[str]):
        self.signal_day = signal_day
        self.tickers = stock_symbols
        self._df: pd.DataFrame = pd.DataFrame()
        self._ranks: pd.DataFrame = pd.DataFrame()
        self._load()

    def _load(self) -> None:
        day = self.signal_day.date() if hasattr(self.signal_day, "date") else self.signal_day
        try:
            df = inst_repo.get_institutional_summary(self.tickers, as_of=day)
        except Exception:
            self._df = pd.DataFrame()
            return

        if df.empty:
            self._df = pd.DataFrame()
            return

        if "ticker" in df.columns:
            df = df.set_index("ticker")

        # Derived columns
        if "shareholders" in df.columns and "shareholders_change" in df.columns:
            df["ownership_trend"] = df["shareholders_change"] / df["shareholders"].replace(0, np.nan)
        else:
            df["ownership_trend"] = np.nan

        if "call_holders" in df.columns and "put_holders" in df.columns:
            df["call_put_ratio"] = df["call_holders"] / df["put_holders"].replace(0, np.nan)
        else:
            df["call_put_ratio"] = np.nan

        if "shares_held_change" in df.columns and "shareholders_change" in df.columns:
            df["accumulation_flag"] = (df["shares_held_change"] > 0) & (df["shareholders_change"] > 0)
        else:
            df["accumulation_flag"] = False

        self._df = df
        self._ranks = self._compute_ranks()

    def _compute_ranks(self) -> pd.DataFrame:
        ranks: dict[str, pd.Series] = {}
        if "shares_held_pct" in self._df.columns:
            ranks["shares_held_pct_rank"] = (
                self._df["shares_held_pct"].rank(pct=True, na_option="keep") * 100
            )
        if "ownership_trend" in self._df.columns:
            ranks["ownership_trend_rank"] = (
                self._df["ownership_trend"].rank(pct=True, na_option="keep") * 100
            )
        return pd.DataFrame(ranks)

    def _get(self, ticker: str, col: str, df: pd.DataFrame | None = None) -> float | None:
        source = df if df is not None else self._df
        if source.empty or ticker not in source.index or col not in source.columns:
            return None
        v = source.loc[ticker, col]
        return None if (v is None or (isinstance(v, float) and np.isnan(v))) else v

    def build_snapshot(self, ticker: str) -> InstitutionalSnapshot:
        cal_raw = self._get(ticker, "calendar_date")
        cal_date = pd.Timestamp(cal_raw) if cal_raw else None

        return InstitutionalSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            calendar_date=cal_date,
            shareholders=self._get(ticker, "shareholders"),
            shareholders_change=self._get(ticker, "shareholders_change"),
            shares_held_pct=self._get(ticker, "shares_held_pct"),
            shares_held_change=self._get(ticker, "shares_held_change"),
            call_holders=self._get(ticker, "call_holders"),
            put_holders=self._get(ticker, "put_holders"),
            ownership_trend=self._get(ticker, "ownership_trend"),
            call_put_ratio=self._get(ticker, "call_put_ratio"),
            accumulation_flag=bool(self._get(ticker, "accumulation_flag") or False),
            shares_held_pct_rank=self._get(ticker, "shares_held_pct_rank", self._ranks),
            ownership_trend_rank=self._get(ticker, "ownership_trend_rank", self._ranks),
        )

    def get_accumulation_flags(self) -> list[str]:
        """Return tickers where institutional accumulation signal is active."""
        if self._df.empty or "accumulation_flag" not in self._df.columns:
            return []
        return list(self._df[self._df["accumulation_flag"]].index)
