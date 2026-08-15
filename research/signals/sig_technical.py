"""Point-in-time technical features with optional signal attachments."""

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
        """Return latest point-in-time technical features from the SQL repository."""
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
        """Attach market-wide percentile ranks for each configured return horizon."""
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
        """Attach 5/20-day returns in excess of the requested benchmark."""
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
        """Benchmark 5/20-day returns, or NaN when its history is too short.

        Returns NaN rather than raising, because too little benchmark history is
        a coverage boundary rather than a fault — the same situation every other
        lookback feature already handles this way. `return_252d` is NaN for a
        security's first year rather than an exception, and an excess return
        against a benchmark that does not yet have 21 sessions is unknowable in
        exactly the same sense. Raising instead made the earliest signal days
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
