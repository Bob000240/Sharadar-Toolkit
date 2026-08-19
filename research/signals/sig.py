"""Shared base class for stateless signal DataFrame services.

The arithmetic every signal service needs: division that survives zeros and
nulls, growth that survives a negative base, and cross-sectional percentile
ranks. All return NaN where the answer is undefined rather than substituting a
number, so a missing fact stays missing all the way to the filter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import database.source.tickers_repo as tickers_repo


class Signals:
    """Common transformations inherited by concrete signal services.

    Methods are stateless and return DataFrames or Series. Concrete signal
    classes provide their own SQL-backed ``get_signals()`` method and optional
    domain-specific ``attach_*()`` transformations.
    """

    @staticmethod
    def safe_div(
        numerator: pd.Series,
        denominator: pd.Series,
        fallback: float = float("nan"),
    ) -> pd.Series:
        """Divide elementwise, substituting ``fallback`` where undefined.

        Undefined means a null on either side or a zero divisor. Return a float
        Series indexed like ``numerator``.
        """
        mask = pd.notna(numerator) & pd.notna(denominator) & (denominator != 0)
        result = pd.Series(fallback, index=numerator.index, dtype=float)
        result[mask] = numerator[mask] / denominator[mask]
        return result

    @staticmethod
    def safe_growth(now, then) -> float:
        """Return the growth from ``then`` to ``now`` as a fraction.

        Divides by the absolute prior value, so a recovery from a negative base
        reads as positive growth. Return NaN when either input is null or the
        base is zero.
        """
        if pd.isna(now) or pd.isna(then) or then == 0:
            return float("nan")
        return (now - then) / abs(then)

    @staticmethod
    def positive_ratio(
        numerator: pd.Series,
        denominator: pd.Series,
    ) -> pd.Series:
        """Divide elementwise where both inputs are finite and strictly positive.

        Stricter than ``safe_div``: a ratio whose sign would be meaningless, such
        as a yield on a negative market cap, is NaN rather than computed. Return
        a float Series indexed like ``numerator``.
        """
        numerator = pd.to_numeric(numerator, errors="coerce")
        denominator = pd.to_numeric(denominator, errors="coerce")
        result = pd.Series(np.nan, index=numerator.index, dtype=float)
        valid = (
            numerator.notna()
            & denominator.notna()
            & np.isfinite(numerator)
            & np.isfinite(denominator)
            & (numerator > 0)
            & (denominator > 0)
        )
        result.loc[valid] = numerator.loc[valid] / denominator.loc[valid]
        return result

    @staticmethod
    def rank_pct(values: pd.Series) -> pd.Series:
        """Return a direction-free cross-sectional percentile in [0, 100].

        Infinities are treated as missing, and ties share the average rank. The
        caller decides which end is good; this only orders.
        """
        values = pd.to_numeric(values, errors="coerce").replace(
            [np.inf, -np.inf],
            np.nan,
        )
        return values.rank(pct=True, method="average") * 100

    @staticmethod
    def rank_within_sector(
        values: pd.Series,
        sectors: pd.Series,
    ) -> pd.Series:
        """Return a direction-free percentile within each sector, in [0, 100].

        Securities with no sector are ranked together under "Unknown" rather
        than dropped.
        """
        values = pd.to_numeric(values, errors="coerce").replace(
            [np.inf, -np.inf],
            np.nan,
        )
        return (
            values.groupby(sectors.fillna("Unknown"))
            .rank(pct=True, method="average")
            .mul(100)
        )

    @classmethod
    def attach_sector_ranks(
        cls,
        frame: pd.DataFrame,
        signals: dict[str, int] | list[str],
        positive_only: tuple = (),
    ) -> pd.DataFrame:
        """Attach a direction-free ``{metric}_sector_pct`` per requested metric.

        ``signals`` is the caller's metric list, or a ``{metric: direction}`` dict whose
        keys alone are read: which metrics matter is a strategy decision.
        ``positive_only`` names metrics whose non-positive values are undefined rather
        than extreme and are masked out of the rank. A metric absent from ``frame``
        yields an all-NaN rank rather than raising.

        :raises ValueError: when ``frame`` carries no ``sector`` column.
        """
        if "sector" not in frame.columns:
            raise ValueError(
                f"sector is required; call {cls.__name__}.attach_sectors() first"
            )

        frame = frame.copy()
        for metric in signals:
            values = frame.get(
                metric,
                pd.Series(np.nan, index=frame.index, dtype=float),
            )
            if metric in positive_only:
                values = pd.to_numeric(values, errors="coerce").where(
                    lambda value: value > 0
                )
            frame[f"{metric}_sector_pct"] = cls.rank_within_sector(
                values,
                frame["sector"],
            )
        return frame

    @staticmethod
    def attach_sectors(frame: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of ``frame`` with a ``sector`` column attached.

        Expects a ticker-indexed frame. Securities the ticker table does not
        cover are labelled "Unknown" rather than left null, so they still group.
        """
        frame = frame.copy()
        if frame.empty:
            frame["sector"] = pd.Series(dtype="object")
            return frame

        metadata = tickers_repo.get(
            tickers=frame.index.astype(str).tolist(),
            table_code="SEP",
        )
        sectors = metadata.drop_duplicates("ticker", keep="last").set_index("ticker")[
            "sector"
        ]
        frame["sector"] = sectors.reindex(frame.index).fillna("Unknown")
        return frame
