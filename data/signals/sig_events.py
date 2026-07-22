"""Point-in-time corporate event rows and optional ticker-level facts."""

from __future__ import annotations

import pandas as pd

import database.source.event_repo as event_repo
from data.signals.sig import Signals


# Sharadar EVENTS codes (separated by "|" in eventcodes).
EARNINGS_CODE = "22"
ACTIVIST_13D_CODE = "35"

EVENT_FACT_COLUMNS = (
    "days_since_last_earnings",
    "days_since_last_activist_13d",
    "recent_event_codes",
)


class EventSignals(Signals):
    """SQL-backed event rows with opt-in ticker-level fact attachments."""

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
        lookback_days: int = 20,
    ) -> pd.DataFrame:
        """Return event rows available in the requested point-in-time window."""
        signal_day = pd.Timestamp(signal_day)
        start = signal_day - pd.Timedelta(days=lookback_days)
        frame = event_repo.get(
            tickers=tickers,
            start_date=str(start.date()),
            end_date=str(signal_day.date()),
        )
        if frame.empty:
            return frame.copy()

        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame

    @classmethod
    def attach_event_facts(
        cls,
        frame: pd.DataFrame,
        tickers: list[str],
        signal_day: pd.Timestamp,
        lookback_days: int = 20,
    ) -> pd.DataFrame:
        """Aggregate raw event rows into objective facts for every ticker.

        Tickers with no events remain present with ``None`` recencies and an
        empty code list. Whether any code is good, bad, or disqualifying belongs
        to the consuming strategy.
        """
        signal_day = pd.Timestamp(signal_day)
        recent_start = signal_day - pd.Timedelta(days=lookback_days)
        rows = []

        if frame.empty:
            grouped: dict[str, pd.DataFrame] = {}
        else:
            history = frame.copy()
            history["date"] = pd.to_datetime(history["date"])
            history = history[
                (history["date"] >= recent_start)
                & (history["date"] <= signal_day)
            ]
            grouped = {
                str(ticker): group
                for ticker, group in history.groupby("ticker", sort=False)
            }

        for ticker in tickers:
            group = grouped.get(str(ticker))
            rows.append(
                {
                    "ticker": ticker,
                    "days_since_last_earnings": cls._days_since_code(
                        group,
                        EARNINGS_CODE,
                        signal_day,
                    ),
                    "days_since_last_activist_13d": cls._days_since_code(
                        group,
                        ACTIVIST_13D_CODE,
                        signal_day,
                    ),
                    "recent_event_codes": cls._event_codes(group),
                }
            )

        if not rows:
            return pd.DataFrame(columns=EVENT_FACT_COLUMNS).rename_axis("ticker")
        return pd.DataFrame(rows).set_index("ticker")

    @staticmethod
    def _has_code(series: pd.Series, code: str) -> pd.Series:
        return series.apply(
            lambda value: (
                code in {item.strip() for item in str(value).split("|")}
                if pd.notna(value)
                else False
            )
        )

    @classmethod
    def _days_since_code(
        cls,
        frame: pd.DataFrame | None,
        code: str,
        signal_day: pd.Timestamp,
    ) -> int | None:
        if frame is None or frame.empty:
            return None
        matches = frame.loc[cls._has_code(frame["eventcodes"], code), "date"]
        if matches.empty:
            return None
        return int((signal_day - matches.max()).days)

    @staticmethod
    def _event_codes(frame: pd.DataFrame | None) -> list[str]:
        if frame is None or frame.empty:
            return []
        codes = {
            code.strip()
            for value in frame["eventcodes"].dropna()
            for code in str(value).split("|")
            if code.strip()
        }
        return sorted(codes)
