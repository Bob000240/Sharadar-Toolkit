"""Point-in-time corporate events and ticker-level event facts.

The window ends the day *before* the signal day, unlike every other source, so
an 8-K filed on the signal day is not visible to a screen run that day. Both
the fetch and the recency arithmetic go through ``_last_visible_day``, which is
what keeps them from drifting apart.

The module names the Sharadar event codes but takes no position on them:
whether a code is good, bad, or disqualifying is a strategy judgment.
"""

from __future__ import annotations

import pandas as pd

import database.source.event_repo as event_repo
from research.signals.sig import Signals


VISIBILITY_LAG_DAYS = 1

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
    """SQL-backed corporate events with opt-in ticker-level facts.

    ``get_signals`` returns the raw filings in the visible window and
    ``attach_event_facts`` reduces them to one row per ticker.
    """

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
        lookback_days: int = 20,
    ) -> pd.DataFrame:
        """Return raw events filed in the window a screen that day may see.

        One row per filing, not one per ticker: several 8-Ks in the window each
        keep their own row and codes.
        """
        last_visible = cls._last_visible_day(signal_day)
        start = last_visible - pd.Timedelta(days=lookback_days)
        frame = event_repo.get(
            tickers=tickers,
            start_date=str(start.date()),
            end_date=str(last_visible.date()),
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
    ) -> pd.DataFrame:
        """Aggregate raw events into objective ticker-level facts.

        :returns: a ticker-indexed frame with one row per *requested* ticker carrying
            earnings recency, 13D recency, and deduplicated event codes. Tickers with
            no events keep their row with null recencies and an empty list, because
            absence of events is a fact rather than missing data.
        """
        signal_day = cls._last_visible_day(signal_day)
        grouped = (
            {}
            if frame.empty
            else {
                str(ticker): group
                for ticker, group in frame.groupby("ticker", sort=False)
            }
        )

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
    def _last_visible_day(signal_day: pd.Timestamp) -> pd.Timestamp:
        """Return the last day whose filings a screen run that day may see."""
        return pd.Timestamp(signal_day) - pd.Timedelta(days=VISIBILITY_LAG_DAYS)

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
