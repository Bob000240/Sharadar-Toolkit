"""Point-in-time indicator rows with optional cross-sectional attachments."""

import pandas as pd

import database.market.fund_repo as fund_repo
import database.market.indicators_repo as indicators_repo
from data.signals.sig import Signals


_RETURN_COLS = ["return_5d", "return_20d", "return_60d", "return_252d"]
_ACTIVE_WINDOW_DAYS = 10
_SECTOR_COUNT = 11


class TechnicalSignals(Signals):
    """SQL-backed technical facts with opt-in DataFrame attachments."""

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Return latest point-in-time indicator rows from the SQL repository."""
        signal_day = pd.Timestamp(signal_day)
        frame = indicators_repo.get_latest_rows(tickers, signal_day)
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
    def attach_sector_features(
        cls,
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Attach median sector returns, 20-day sector rank, and relative returns."""
        if "sector" not in frame.columns:
            raise ValueError(
                "sector is required; call TechnicalSignals.attach_sectors() first"
            )

        frame = frame.copy()
        sector_table = cls._compute_sector_table(frame, pd.Timestamp(signal_day))
        frame = frame.join(sector_table, on="sector")
        frame["sector_relative_5d"] = frame["return_5d"] - frame["sector_return_5d"]
        frame["sector_relative_20d"] = frame["return_20d"] - frame["sector_return_20d"]
        frame["sector_score"] = (
            1.0 - (frame["sector_rank_20d"] - 1) / (_SECTOR_COUNT - 1)
        ).fillna(0.5)
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
    def _compute_sector_table(
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        recent = frame[
            pd.to_datetime(frame["date"])
            >= signal_day - pd.Timedelta(days=_ACTIVE_WINDOW_DAYS)
        ]
        recent = recent[recent["sector"] != "Unknown"]

        sector_table = recent.groupby("sector")[_RETURN_COLS].median()
        sector_table["sector_rank_20d"] = sector_table["return_20d"].rank(
            ascending=False,
            method="min",
        )
        return sector_table.rename(
            columns={column: f"sector_{column}" for column in _RETURN_COLS}
        )

    @staticmethod
    def _calculate_fund_returns(
        ticker: str,
        signal_day: pd.Timestamp,
    ) -> pd.Series:
        lookback = signal_day - pd.Timedelta(days=45)
        prices = fund_repo.get(
            tickers=[ticker],
            start_date=str(lookback.date()),
            end_date=str(signal_day.date()),
        )
        if prices.empty:
            raise ValueError(
                f"No fund price data for {ticker} as of {signal_day.date()}"
            )

        closes = prices.sort_values("date")["close"].to_numpy()
        if len(closes) < 21:
            raise ValueError(
                f"Fewer than 21 fund price rows for {ticker} as of {signal_day.date()}"
            )

        return pd.Series(
            {
                "return_5d": closes[-1] / closes[-6] - 1,
                "return_20d": closes[-1] / closes[-21] - 1,
            }
        )
