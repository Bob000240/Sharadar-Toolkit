"""Point-in-time macro rows with optional direction and labor attachments."""

from __future__ import annotations

import numpy as np
import pandas as pd

import database.market.macro_repo as macro_repo
from data.signals.sig import Signals


CHANGE_WINDOWS = {
    "yield_curve_change_60d": ("yield_curve_2_10", 60),
    "real_yield_change_20d": ("real_yield_10y", 20),
    "spread_hy_change_20d": ("spread_hy", 20),
    "spread_ig_change_20d": ("spread_ig", 20),
    "vix_change_20d": ("vix", 20),
    "cpi_yoy_change_3m": ("cpi_yoy", 90),
}


class MacroSignals(Signals):
    """SQL-backed macro history with opt-in derived fact attachments."""

    @classmethod
    def get_signals(
        cls,
        signal_day: pd.Timestamp,
        history_days: int = 200,
    ) -> pd.DataFrame:
        """Return raw macro history available on or before the signal day."""
        signal_day = pd.Timestamp(signal_day)
        start = signal_day - pd.Timedelta(days=history_days)
        frame = macro_repo.get(
            start_date=str(start.date()),
            end_date=str(signal_day.date()),
        )
        if frame.empty:
            return frame.copy()

        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.sort_values("date").reset_index(drop=True)

    @classmethod
    def attach_directional_changes(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach calendar-lookback changes to every macro history row."""
        frame = cls._prepare_history(frame)
        for output, (column, days) in CHANGE_WINDOWS.items():
            frame[output] = cls._calendar_change(frame, column, days)
        return frame

    @classmethod
    def attach_claims_stats(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach four-week claims averages and 13-week percentage changes."""
        frame = cls._prepare_history(frame)
        frame["claims_4w_avg"] = np.nan
        frame["claims_change_13w_pct"] = np.nan
        if frame.empty or "claims_as_of" not in frame.columns:
            return frame

        claims = frame[["claims_as_of", "jobless_claims"]].dropna().copy()
        if claims.empty:
            return frame

        claims["claims_as_of"] = pd.to_datetime(claims["claims_as_of"])
        claims["jobless_claims"] = pd.to_numeric(
            claims["jobless_claims"],
            errors="coerce",
        )
        claims = claims.dropna(subset=["jobless_claims"])
        claims = claims.sort_values("claims_as_of").drop_duplicates(
            "claims_as_of",
            keep="last",
        )
        for index, row in frame.iterrows():
            visible = claims[claims["claims_as_of"] <= row["date"]]
            if visible.empty:
                continue

            current = float(visible["jobless_claims"].tail(4).mean())
            prior_cutoff = row["date"] - pd.Timedelta(weeks=13)
            prior = visible.loc[
                visible["claims_as_of"] <= prior_cutoff,
                "jobless_claims",
            ].tail(4)
            frame.at[index, "claims_4w_avg"] = current
            if not prior.empty and prior.mean() != 0:
                frame.at[index, "claims_change_13w_pct"] = (
                    current / float(prior.mean()) - 1
                )
        return frame

    @classmethod
    def _prepare_history(cls, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        if frame.empty:
            return frame
        if "date" not in frame.columns:
            raise ValueError("date is required in the macro signal frame")
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.sort_values("date").reset_index(drop=True)

    @staticmethod
    def _calendar_change(
        frame: pd.DataFrame,
        column: str,
        days: int,
    ) -> pd.Series:
        changes = pd.Series(np.nan, index=frame.index, dtype=float)
        if column not in frame.columns or frame.empty:
            return changes

        known = frame[["date", column]].dropna().sort_values("date")
        if known.empty:
            return changes

        dates = known["date"].to_numpy(dtype="datetime64[ns]")
        values = pd.to_numeric(known[column], errors="coerce").to_numpy()
        for index, row in frame.iterrows():
            current = pd.to_numeric(
                pd.Series([row[column]]),
                errors="coerce",
            ).iloc[0]
            if pd.isna(current):
                continue
            target = np.datetime64(row["date"] - pd.Timedelta(days=days))
            prior_position = dates.searchsorted(target, side="right") - 1
            if prior_position >= 0 and np.isfinite(values[prior_position]):
                changes.at[index] = float(current) - float(values[prior_position])
        return changes
