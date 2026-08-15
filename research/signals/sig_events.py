"""Point-in-time corporate event facts, one row per ticker.

The lookback ends the day *before* the signal day, unlike every other signal
source, which reads up to and including it. An 8-K filed on the signal day is
therefore not visible to a screen run that same day.

The module names the Sharadar event codes but takes no position on them:
whether a code is good, bad, or disqualifying is a strategy judgment.
"""

from __future__ import annotations

import pandas as pd

import database.source.event_repo as event_repo
from research.signals.sig import Signals


EARNINGS_CODE = "22"
ACTIVIST_13D_CODE = "35"
DELISTING_CODE = "31"
BANKRUPTCY_CODE = "13"
RESTATEMENT_CODE = "42"
LATE_FILING_CODE = "36"
MATERIAL_IMPAIRMENT_CODE = "26"

EVENT_FACT_COLUMNS = (
    "days_since_last_earnings",
    "days_since_last_activist_13d",
    "recent_event_codes",
)


class EventSignals(Signals):
    """SQL-backed corporate-event facts, one row per ticker.

    The only public method is ``attach_event_facts``, which both fetches and
    aggregates. Unlike the other signal services there is no ``get_signals`` /
    ``attach_*`` split, because events are never useful as raw rows.
    """

    @classmethod
    def attach_event_facts(
        cls,
        tickers: list[str],
        signal_day: pd.Timestamp,
        lookback_days: int = 20,
    ) -> pd.DataFrame:
        """Aggregate each ticker's recent corporate events into objective facts.

        The window is the ``lookback_days`` ending one day before
        ``signal_day``, so nothing filed on the signal day itself is visible.

        Return a ticker-indexed frame with one row per *requested* ticker,
        carrying earnings recency, 13D recency, and the deduplicated list of
        event codes. Tickers with no events keep their row with null recencies
        and an empty list, because absence of events is a fact rather than
        missing data.
        """
        signal_day = pd.Timestamp(signal_day) - pd.Timedelta(days=1)
        start = signal_day - pd.Timedelta(days=lookback_days)
        frame = event_repo.get(
            tickers=tickers,
            start_date=str(start.date()),
            end_date=str(signal_day.date()),
        )

        if frame.empty:
            grouped: dict[str, pd.DataFrame] = {}
        else:
            frame = frame.copy()
            frame["date"] = pd.to_datetime(frame["date"])
            grouped = {
                str(ticker): group
                for ticker, group in frame.groupby("ticker", sort=False)
            }

        rows = []
        for ticker in tickers:
            group = grouped.get(str(ticker))
            rows.append(
                {
                    "ticker": ticker,
                    "days_since_last_earnings": cls._days_since_code(
                        group, EARNINGS_CODE, signal_day
                    ),
                    "days_since_last_activist_13d": cls._days_since_code(
                        group, ACTIVIST_13D_CODE, signal_day
                    ),
                    "recent_event_codes": cls._event_codes(group),
                }
            )

        if not rows:
            return pd.DataFrame(columns=EVENT_FACT_COLUMNS).rename_axis("ticker")
        return pd.DataFrame(rows).set_index("ticker")

    @staticmethod
    def _has_code(series: pd.Series, code: str) -> pd.Series:
        """Mark rows whose pipe-delimited code string contains ``code``."""
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
        """Return days since the most recent event carrying ``code``.

        Return None when the ticker has no events at all, or none with that
        code, in the window.
        """
        if frame is None or frame.empty:
            return None
        matches = frame.loc[cls._has_code(frame["eventcodes"], code), "date"]
        if matches.empty:
            return None
        return int((signal_day - matches.max()).days)

    @staticmethod
    def _event_codes(frame: pd.DataFrame | None) -> list[str]:
        """Return the sorted, deduplicated event codes in the window."""
        if frame is None or frame.empty:
            return []
        codes = {
            code.strip()
            for value in frame["eventcodes"].dropna()
            for code in str(value).split("|")
            if code.strip()
        }
        return sorted(codes)
