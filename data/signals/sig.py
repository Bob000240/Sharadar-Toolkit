"""Shared base class for stateless signal DataFrame services."""

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

    @classmethod
    def attach_sector_ranks(
        cls,
        frame: pd.DataFrame,
        signals: dict[str, int] | list[str],
        positive_only: tuple = (),
        negative_only: tuple = (),
    ) -> pd.DataFrame:
        """Attach `{metric}_sector_pct` for each requested metric, direction-free.

        `signals` is the CALLER's own metric list (or {metric: direction} dict —
        only the keys are used here) — which metrics matter is a strategy
        decision, not this module's. A metric absent from `frame` yields an
        all-NaN rank rather than raising.

        `positive_only` names metrics where a non-positive value is UNDEFINED
        (e.g. a loss-maker's PE), not merely extreme, and is masked out of the
        rank rather than ranked as "cheapest".
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
            if metric in negative_only:
                values = pd.to_numeric(values, errors="coerce").where(
                    lambda value: value < 0
                )
            frame[f"{metric}_sector_pct"] = cls.rank_within_sector(
                values,
                frame["sector"],
            )
        return frame

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
