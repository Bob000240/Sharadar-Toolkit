"""Point-in-time institutional holding rows and optional holding facts."""

from __future__ import annotations

import numpy as np
import pandas as pd

import database.source.institutional_repo as institutional_repo
from data.signals.sig import Signals


# 13F reports are due 45 days after quarter end. The database does not retain
# each filing's actual accepted timestamp, so this conservative availability
# estimate prevents future quarter holdings from leaking into a signal day.
FILING_DELAY_DAYS = 45
SHARE_SECURITY_TYPE = "SHR"

HOLDING_FACT_COLUMNS = (
    "quarter_end",
    "assumed_available_from",
    "stale_days",
    "availability_is_estimated",
    "total_holders",
    "total_value_b",
    "total_units",
    "holders_change",
    "value_change_pct",
    "units_change_pct",
    "new_holders",
    "closed_positions",
)


class InstitutionalSignals(Signals):
    """SQL-backed 13F rows with opt-in ticker-level fact attachments."""

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
        history_days: int = 200,
    ) -> pd.DataFrame:
        """Return raw holdings from conservatively available report quarters."""
        signal_day = pd.Timestamp(signal_day)
        available_quarter_cutoff = signal_day - pd.Timedelta(
            days=FILING_DELAY_DAYS
        )
        start = available_quarter_cutoff - pd.Timedelta(days=history_days)
        frame = institutional_repo.get(
            tickers=tickers,
            start_date=str(start.date()),
            end_date=str(available_quarter_cutoff.date()),
        )
        if frame.empty:
            return frame.copy()

        frame = frame.copy()
        frame["calendardate"] = pd.to_datetime(frame["calendardate"])
        return frame

    @classmethod
    def attach_holding_facts(
        cls,
        frame: pd.DataFrame,
        tickers: list[str],
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Aggregate raw 13F rows into latest-quarter and QoQ facts."""
        signal_day = pd.Timestamp(signal_day)
        if frame.empty:
            grouped: dict[str, pd.DataFrame] = {}
        else:
            holdings = frame.copy()
            holdings["calendardate"] = pd.to_datetime(holdings["calendardate"])
            holdings = holdings[holdings["securitytype"] == SHARE_SECURITY_TYPE]
            grouped = {
                str(ticker): group
                for ticker, group in holdings.groupby("ticker", sort=False)
            }

        rows = [
            {
                "ticker": ticker,
                **cls._aggregate_ticker(grouped.get(str(ticker)), signal_day),
            }
            for ticker in tickers
        ]
        if not rows:
            return pd.DataFrame(columns=HOLDING_FACT_COLUMNS).rename_axis("ticker")
        return pd.DataFrame(rows).set_index("ticker")

    @classmethod
    def _aggregate_ticker(
        cls,
        frame: pd.DataFrame | None,
        signal_day: pd.Timestamp,
    ) -> dict:
        empty = {
            "quarter_end": None,
            "assumed_available_from": None,
            "stale_days": None,
            "availability_is_estimated": True,
            "total_holders": 0,
            "total_value_b": 0.0,
            "total_units": 0.0,
            "holders_change": 0,
            "value_change_pct": np.nan,
            "units_change_pct": np.nan,
            "new_holders": 0,
            "closed_positions": 0,
        }
        if frame is None or frame.empty:
            return empty

        quarters = sorted(frame["calendardate"].dropna().unique())
        if not quarters:
            return empty

        latest_quarter = pd.Timestamp(quarters[-1])
        current = frame[frame["calendardate"] == latest_quarter]
        current_holders = current["investorname"].nunique()
        current_value = float(
            pd.to_numeric(current["value"], errors="coerce").fillna(0).sum()
        )
        current_units = float(
            pd.to_numeric(current["units"], errors="coerce").fillna(0).sum()
        )
        facts = {
            **empty,
            "quarter_end": latest_quarter,
            "assumed_available_from": latest_quarter
            + pd.Timedelta(days=FILING_DELAY_DAYS),
            "stale_days": int(
                (signal_day.normalize() - latest_quarter.normalize()).days
            ),
            "total_holders": int(current_holders),
            "total_value_b": current_value / 1e9,
            "total_units": current_units,
        }
        if len(quarters) < 2:
            return facts

        prior = frame[frame["calendardate"] == pd.Timestamp(quarters[-2])]
        prior_holders = prior["investorname"].nunique()
        prior_value = float(
            pd.to_numeric(prior["value"], errors="coerce").fillna(0).sum()
        )
        prior_units = float(
            pd.to_numeric(prior["units"], errors="coerce").fillna(0).sum()
        )
        current_names = set(current["investorname"].dropna())
        prior_names = set(prior["investorname"].dropna())
        facts.update(
            {
                "holders_change": int(current_holders - prior_holders),
                "value_change_pct": cls.safe_growth(current_value, prior_value),
                "units_change_pct": cls.safe_growth(current_units, prior_units),
                "new_holders": len(current_names - prior_names),
                "closed_positions": len(prior_names - current_names),
            }
        )
        return facts
