"""
Shared helpers for the signal layer.

Every derived column/feature is created by a helper like these — the signal
Model/Snapshot "shapes" orchestrate and expose, they do not compute columns
inline.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

import database.market.tickers_repo as tickers_repo

DEFAULT_MIN_SECTOR_RANK_SIZE = 10


def python_scalar(value):
    """Convert a numpy scalar to a native Python scalar (pass through otherwise)."""
    if isinstance(value, np.generic):
        return value.item()
    return value


def safe_div(
    numerator: pd.Series, denominator: pd.Series, fallback: float = float("nan")
) -> pd.Series:
    """Elementwise a/b, NaN where either side is missing or the denominator is 0."""
    mask = pd.notna(numerator) & pd.notna(denominator) & (denominator != 0)
    result = pd.Series(fallback, index=numerator.index, dtype=float)
    result[mask] = numerator[mask] / denominator[mask]
    return result


def safe_growth(now, then) -> float:
    """Scalar growth (now-then)/|then|; NaN if either is missing or then == 0."""
    if pd.isna(now) or pd.isna(then) or then == 0:
        return float("nan")
    return (now - then) / abs(then)


def positive_inverse(values: pd.Series) -> pd.Series:
    """1/x, only where x is finite and strictly positive (else NaN)."""
    values = pd.to_numeric(values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.notna() & np.isfinite(values) & (values > 0)
    result.loc[valid] = 1.0 / values.loc[valid]
    return result


def positive_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """numerator/denominator, only where both are finite and strictly positive."""
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


def rank_pct(values: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank in [0, 100] (average method for ties)."""
    return pd.to_numeric(values, errors="coerce").rank(pct=True, method="average") * 100


def rank_within_sector(
    values: pd.Series,
    sectors: pd.Series,
    min_sector_size: int = DEFAULT_MIN_SECTOR_RANK_SIZE,
) -> pd.Series:
    """Percentile rank within sector, falling back to a market-wide rank for
    sectors with fewer than `min_sector_size` valid observations."""
    values = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    sectors = sectors.fillna("Unknown")
    sector_rank = values.groupby(sectors).rank(pct=True, method="average") * 100
    sector_count = values.notna().groupby(sectors).transform("sum")
    market_rank = values.rank(pct=True, method="average") * 100
    return sector_rank.where(sector_count >= min_sector_size, market_rank)


def attach_sectors(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach ticker sectors to a DataFrame indexed by ticker."""
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
