"""Point-in-time corporate event rows and optional ticker-level facts."""

from __future__ import annotations

import pandas as pd

import database.source.event_repo as event_repo
from data.signals.sig import Signals


# Sharadar EVENTS codes (separated by "|" in eventcodes).
EARNINGS_CODE = "22"              # Results of Operations and Financial Condition
ACTIVIST_13D_CODE = "35"          # Schedule 13D Filing
DELISTING_CODE = "31"             # Notice of Delisting or Failure to Satisfy a
                                   # Continued Listing Rule or Standard
BANKRUPTCY_CODE = "13"            # Bankruptcy or Receivership
RESTATEMENT_CODE = "42"           # Non-Reliance on Previously Issued Financial
                                   # Statements or a Related Audit Report
LATE_FILING_CODE = "36"           # Notice under Rule 12b25 of inability to
                                   # timely file a 10-K or 10-Q
MATERIAL_IMPAIRMENT_CODE = "26"   # Material Impairments

EVENT_FACT_COLUMNS = (
    "days_since_last_earnings",
    "days_since_last_activist_13d",
    "recent_event_codes",
)


class EventSignals(Signals):
    """SQL-backed corporate-event facts, one row per ticker.

    Unlike the other signal services, events are never consumed as raw rows —
    they're only useful once aggregated per ticker — so there is a single
    method that both fetches and aggregates, rather than the usual
    get_signals() + attach_*() split.
    """

    @classmethod
    def attach_event_facts(
        cls,
        tickers: list[str],
        signal_day: pd.Timestamp,
        lookback_days: int = 20,
    ) -> pd.DataFrame:
        """Fetch each ticker's corporate events within `lookback_days` of
        `signal_day` (point-in-time) and aggregate them into objective facts —
        one row per requested ticker: earnings and 13D recency, plus the deduped
        list of recent event codes.

        Tickers with no events remain present with ``None`` recencies and an
        empty code list. Whether any code is good, bad, or disqualifying belongs
        to the consuming strategy.
        """
        signal_day = pd.Timestamp(signal_day) - pd.Timedelta(days=1)  # point-in-time
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
