"""Point-in-time technical features with optional signal attachments.

Reads the stored per-session feature rows and derives the columns that only
make sense cross-sectionally or against a benchmark. Everything is bounded by
the signal day, so a feature row filed after it is never visible.
"""

import pandas as pd

import database.source.fund_repo as fund_repo
import database.source.technical_features_repo as technical_features_repo
from research.signals.sig import Signals


_RETURN_COLS = ["return_5d", "return_20d", "return_60d", "return_252d"]


class TechnicalSignals(Signals):
    """SQL-backed technical facts with opt-in DataFrame attachments."""

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Return each ticker's most recent feature row on or before the day.

        Passing ``tickers`` preserves the caller's order and silently drops
        names with no row at all. Return a ticker-indexed frame, empty with no
        columns when the date predates the stored features.
        """
        signal_day = pd.Timestamp(signal_day)
        frame = technical_features_repo.get_latest_rows(tickers, signal_day)
        if frame.empty:
            return pd.DataFrame().rename_axis("ticker")

        frame = frame.set_index("ticker")
        if tickers is not None:
            ordered = [ticker for ticker in tickers if ticker in frame.index]
            frame = frame.loc[ordered]
        return frame.copy()

    @classmethod
    def attach_return_percentiles(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach a market-wide percentile rank per configured return horizon.

        Ranked across whatever population ``frame`` holds, so the percentiles
        mean "within this frame" rather than "within the market".
        """
        frame = frame.copy()
        for column in _RETURN_COLS:
            frame[f"{column}_percentile"] = cls.rank_pct(frame[column])
        return frame

    @classmethod
    def attach_market_relative_returns(
        cls,
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
        benchmark_ticker: str = "SPY",
    ) -> pd.DataFrame:
        """Attach 5- and 20-day returns in excess of a benchmark fund.

        The benchmark return is a single scalar per horizon, subtracted from
        every row. Both columns are NaN when the benchmark lacks the history.
        """
        frame = frame.copy()
        benchmark = cls._calculate_fund_returns(
            benchmark_ticker,
            pd.Timestamp(signal_day),
        )
        frame["excess_return_5d"] = frame["return_5d"] - benchmark["return_5d"]
        frame["excess_return_20d"] = frame["return_20d"] - benchmark["return_20d"]
        return frame

    @staticmethod
    def _calculate_fund_returns(
        ticker: str,
        signal_day: pd.Timestamp,
    ) -> pd.Series:
        """Return the benchmark's 5- and 20-day returns, or NaN if too short.

        NaN rather than an exception, because too little benchmark history is a
        coverage boundary rather than a fault, and every other lookback feature
        already behaves this way: ``return_252d`` is NaN for a security's first
        year rather than an error. Raising instead made the earliest signal days
        abort a whole walk-forward rather than yield an empty population.
        """
        lookback = signal_day - pd.Timedelta(days=45)
        prices = fund_repo.get(
            tickers=[ticker],
            start_date=str(lookback.date()),
            end_date=str(signal_day.date()),
        )
        unknown = pd.Series({"return_5d": float("nan"), "return_20d": float("nan")})
        if prices.empty:
            return unknown

        closes = prices.sort_values("date")["close"].to_numpy()
        if len(closes) < 21:
            return unknown

        return pd.Series(
            {
                "return_5d": closes[-1] / closes[-6] - 1,
                "return_20d": closes[-1] / closes[-21] - 1,
            }
        )
