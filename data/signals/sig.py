"""Shared base class for stateless signal DataFrame services."""

from __future__ import annotations

import numpy as np
import pandas as pd

import database.market.tickers_repo as tickers_repo


class Signals:
    """Common transformations inherited by concrete signal services.

    Methods are stateless and return DataFrames or Series. Concrete signal
    classes provide their own SQL-backed ``get_signals()`` method and optional
    domain-specific ``attach_*()`` transformations.
    """

    @staticmethod
    def python_scalar(value):
        """Convert a NumPy scalar to a native Python scalar."""
        if isinstance(value, np.generic):
            return value.item()
        return value

    @staticmethod
    def safe_div(
        numerator: pd.Series,
        denominator: pd.Series,
        fallback: float = float("nan"),
    ) -> pd.Series:
        """Elementwise a/b, with fallback for missing values or zero divisors."""
        mask = pd.notna(numerator) & pd.notna(denominator) & (denominator != 0)
        result = pd.Series(fallback, index=numerator.index, dtype=float)
        result[mask] = numerator[mask] / denominator[mask]
        return result

    @staticmethod
    def safe_growth(now, then) -> float:
        """Return (now-then)/|then|, or NaN when the inputs are invalid."""
        if pd.isna(now) or pd.isna(then) or then == 0:
            return float("nan")
        return (now - then) / abs(then)

    @staticmethod
    def positive_ratio(
        numerator: pd.Series,
        denominator: pd.Series,
    ) -> pd.Series:
        """Return numerator/denominator where both inputs are finite and positive."""
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
        """Cross-sectional percentile rank in [0, 100]."""
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
        """Percentile rank within each sector, in [0, 100]."""
        values = pd.to_numeric(values, errors="coerce").replace(
            [np.inf, -np.inf],
            np.nan,
        )
        return (
            values.groupby(sectors.fillna("Unknown"))
            .rank(pct=True, method="average")
            .mul(100)
        )

    @staticmethod
    def attach_sectors(frame: pd.DataFrame) -> pd.DataFrame:
        """Return a copy with ticker-sector metadata attached."""
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
