"""Point-in-time institutional ownership, one row per ticker.

A 13F is filed up to 45 days after the quarter it reports on, so a quarter is
treated as unavailable until that lag has passed. ``FILING_DELAY_DAYS`` encodes
the assumption; ``inst_availability_is_estimated`` records that it is one.

Sourced from SF3A, which the vendor summarises by ticker. Holder identity is no
part of that summary, so who holds a position, and who opened or closed one,
cannot be answered from these facts at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import database.source.institutional_repo as institutional_repo
from research.signals.sig import Signals


FILING_DELAY_DAYS = 45

PROVENANCE_COLUMNS = (
    "inst_quarter_end",
    "inst_available_from",
    "inst_availability_is_estimated",
)

OWNERSHIP_FACT_COLUMNS = PROVENANCE_COLUMNS + (
    "inst_stale_days",
    "inst_holders",
    "inst_units",
    "inst_value",
    "inst_pct_of_all_holdings",
    "inst_put_call_ratio",
    "inst_holders_change",
    "inst_units_change_pct",
    "inst_value_change_pct",
)


class InstitutionalSignals(Signals):
    """Quarterly 13F ownership reduced to ticker-level facts.

    ``get_signals`` returns the stored quarters conservatively assumed available
    and ``attach_ownership_facts`` reduces them to one row per requested ticker,
    which is the shape the filter and ranking path consumes.
    """

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
        history_days: int = 200,
    ) -> pd.DataFrame:
        """Return stored quarters conservatively assumed available on that day.

        Quarters ending within ``FILING_DELAY_DAYS`` of the signal day are
        excluded, since their filings may not have appeared yet. The default
        history spans two quarters, enough for a quarter-over-quarter change.
        """
        signal_day = pd.Timestamp(signal_day)
        available_quarter_cutoff = signal_day - pd.Timedelta(days=FILING_DELAY_DAYS)
        start = available_quarter_cutoff - pd.Timedelta(days=history_days)
        frame = institutional_repo.get(
            tickers=tickers,
            start_date=str(start.date()),
            end_date=str(available_quarter_cutoff.date()),
        )
        if frame.empty:
            return frame.copy()

        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame

    @classmethod
    def attach_ownership_facts(
        cls,
        frame: pd.DataFrame,
        tickers: list[str],
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Reduce the available quarters to one row per requested ticker.

        A ticker no institution reported keeps its row with null facts, since
        absence of a 13F is not the same fact as an ownership level of zero.
        """
        signal_day = pd.Timestamp(signal_day)
        grouped = (
            {}
            if frame.empty
            else {
                str(ticker): group.sort_values("date")
                for ticker, group in frame.groupby("ticker", sort=False)
            }
        )
        rows = [
            {
                "ticker": ticker,
                **cls._ticker_facts(grouped.get(str(ticker)), signal_day),
            }
            for ticker in tickers
        ]
        if not rows:
            return pd.DataFrame(columns=OWNERSHIP_FACT_COLUMNS).rename_axis("ticker")
        return pd.DataFrame(rows).set_index("ticker")

    @classmethod
    def _ticker_facts(
        cls,
        frame: pd.DataFrame | None,
        signal_day: pd.Timestamp,
    ) -> dict:
        """Reduce one ticker's available quarters to a fact dict.

        Quarter-over-quarter changes need two quarters and stay null with only
        one, rather than reading as no change.
        """
        empty = dict.fromkeys(OWNERSHIP_FACT_COLUMNS, np.nan)
        empty["inst_availability_is_estimated"] = True
        if frame is None or frame.empty:
            return empty

        latest = frame.iloc[-1]
        quarter_end = pd.Timestamp(latest["date"])
        facts = {
            **empty,
            "inst_quarter_end": quarter_end,
            "inst_available_from": quarter_end + pd.Timedelta(days=FILING_DELAY_DAYS),
            "inst_stale_days": int(
                (signal_day.normalize() - quarter_end.normalize()).days
            ),
            "inst_holders": cls._number(latest["shrholders"]),
            "inst_units": cls._number(latest["shrunits"]),
            "inst_value": cls._number(latest["shrvalue"]),
            "inst_pct_of_all_holdings": cls._number(latest["percentoftotal"]),
            "inst_put_call_ratio": cls._ratio(latest["putvalue"], latest["cllvalue"]),
        }
        if len(frame) < 2:
            return facts

        prior = frame.iloc[-2]
        facts.update(
            {
                "inst_holders_change": cls._number(latest["shrholders"])
                - cls._number(prior["shrholders"]),
                "inst_units_change_pct": cls.safe_growth(
                    cls._number(latest["shrunits"]), cls._number(prior["shrunits"])
                ),
                "inst_value_change_pct": cls.safe_growth(
                    cls._number(latest["shrvalue"]), cls._number(prior["shrvalue"])
                ),
            }
        )
        return facts

    @staticmethod
    def _number(value) -> float:
        """Return ``value`` as a float, or NaN where the vendor left it null."""
        return float(pd.to_numeric(value, errors="coerce"))

    @staticmethod
    def _ratio(numerator, denominator) -> float:
        """Divide two vendor amounts, returning NaN where the answer is undefined."""
        numerator = float(pd.to_numeric(numerator, errors="coerce"))
        denominator = float(pd.to_numeric(denominator, errors="coerce"))
        if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
            return float("nan")
        return numerator / denominator
