"""
Macro facts, point-in-time. This module is a fact source, not a classifier: it
emits levels, directional changes, and the release date of each input. Judgment
about what those numbers mean (regime, risk posture) belongs to the agent, which
reads these facts as context. Consistent with the rest of the signal layer —
numbers out, no verdicts.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, fields

import database.market.macro_repo as macro_repo


def _python_scalar(v):
    if isinstance(v, np.generic):
        return v.item()
    return v


def _is_known(value) -> bool:
    return value is not None and not pd.isna(value)


@dataclass
class MacroSnapshot:
    signal_day: pd.Timestamp

    # Yield curve
    yield_2y: float
    yield_10y: float
    yield_curve_2_10: float  # 10y - 2y
    yield_curve_3m_10: float  # 10y - 3m

    # Real yields (TIPS)
    real_yield_10y: float

    # Breakeven inflation (market expectations)
    breakeven_10y: float

    # Policy
    fed_funds_rate: float

    # Credit spreads (percent, e.g. 3.5 = 350 bps)
    spread_hy: float
    spread_ig: float

    # Inflation
    cpi_yoy: float
    cpi_core_yoy: float

    # Labor
    unemployment_rate: float
    jobless_claims: float

    # Risk sentiment
    vix: float

    # Dollar & commodities
    dxy: float
    oil_wti: float

    # Directional changes, in percentage points unless noted otherwise
    yield_curve_change_60d: float = np.nan
    real_yield_change_20d: float = np.nan
    spread_hy_change_20d: float = np.nan
    spread_ig_change_20d: float = np.nan
    vix_change_20d: float = np.nan
    cpi_yoy_change_3m: float = np.nan
    claims_4w_avg: float = np.nan
    claims_change_13w_pct: float = np.nan

    # Date each input group was actually available
    rates_as_of: pd.Timestamp | None = None
    credit_as_of: pd.Timestamp | None = None
    inflation_as_of: pd.Timestamp | None = None
    unemployment_as_of: pd.Timestamp | None = None
    claims_as_of: pd.Timestamp | None = None
    volatility_as_of: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        for f in fields(self):
            setattr(self, f.name, _python_scalar(getattr(self, f.name)))

    def as_of_dates(self) -> dict[str, str | None]:
        names = (
            "rates_as_of",
            "credit_as_of",
            "inflation_as_of",
            "unemployment_as_of",
            "claims_as_of",
            "volatility_as_of",
        )
        return {
            name.removesuffix("_as_of"): (
                pd.Timestamp(getattr(self, name)).date().isoformat()
                if _is_known(getattr(self, name))
                else None
            )
            for name in names
        }

    def to_dict(self) -> dict:
        """The point-in-time facts, serialized for the agent. Numbers only, no
        judgment. Unavailable values (NaN) become null; each input group carries
        the date it was actually released."""
        skip = {
            "signal_day",
            "rates_as_of",
            "credit_as_of",
            "inflation_as_of",
            "unemployment_as_of",
            "claims_as_of",
            "volatility_as_of",
        }
        facts: dict = {}
        for f in fields(self):
            if f.name in skip:
                continue
            value = getattr(self, f.name)
            facts[f.name] = value if _is_known(value) else None
        facts["signal_day"] = pd.Timestamp(self.signal_day).date().isoformat()
        facts["as_of"] = self.as_of_dates()
        return facts


class MacroModel:
    def __init__(self, signal_day: pd.Timestamp):
        self.signal_day = signal_day
        self._history: pd.DataFrame | None = None
        self._row: pd.Series | None = None
        self.load_data()

    def load_data(self) -> None:
        start = (self.signal_day - pd.Timedelta(days=200)).date().isoformat()
        df = macro_repo.get(
            start_date=start,
            end_date=str(self.signal_day.date()),
        )
        if df.empty:
            raise ValueError(f"No macro data as of {self.signal_day.date()}")
        df["date"] = pd.to_datetime(df["date"])
        self._history = df.sort_values("date")
        self._row = self._history.iloc[-1]

    def _change(self, column: str, days: int) -> float:
        current = self._row.get(column)
        target = self.signal_day - pd.Timedelta(days=days)
        prior = self._history.loc[
            self._history["date"] <= target, column
        ].dropna()
        if not _is_known(current) or prior.empty:
            return np.nan
        return float(current) - float(prior.iloc[-1])

    def _claims_stats(self) -> tuple[float, float]:
        if "claims_as_of" not in self._history:
            return np.nan, np.nan

        claims = self._history[["claims_as_of", "jobless_claims"]].dropna().copy()
        if claims.empty:
            return np.nan, np.nan
        claims["claims_as_of"] = pd.to_datetime(claims["claims_as_of"])
        claims = (
            claims.sort_values("claims_as_of")
            .drop_duplicates("claims_as_of", keep="last")
        )
        current = float(claims["jobless_claims"].tail(4).mean())
        cutoff = self.signal_day - pd.Timedelta(weeks=13)
        prior = claims.loc[claims["claims_as_of"] <= cutoff, "jobless_claims"].tail(4)
        if prior.empty or prior.mean() == 0:
            return current, np.nan
        return current, current / float(prior.mean()) - 1

    def build_snapshot(self) -> MacroSnapshot:
        r = self._row
        claims_4w_avg, claims_change_13w_pct = self._claims_stats()
        return MacroSnapshot(
            signal_day=self.signal_day,
            yield_2y=r["yield_2y"],
            yield_10y=r["yield_10y"],
            yield_curve_2_10=r["yield_curve_2_10"],
            yield_curve_3m_10=r["yield_curve_3m_10"],
            real_yield_10y=r["real_yield_10y"],
            breakeven_10y=r["breakeven_10y"],
            fed_funds_rate=r["fed_funds_rate"],
            spread_hy=r["spread_hy"],
            spread_ig=r["spread_ig"],
            cpi_yoy=r["cpi_yoy"],
            cpi_core_yoy=r["cpi_core_yoy"],
            unemployment_rate=r["unemployment_rate"],
            jobless_claims=r["jobless_claims"],
            vix=r["vix"],
            dxy=r["dxy"],
            oil_wti=r["oil_wti"],
            yield_curve_change_60d=self._change("yield_curve_2_10", 60),
            real_yield_change_20d=self._change("real_yield_10y", 20),
            spread_hy_change_20d=self._change("spread_hy", 20),
            spread_ig_change_20d=self._change("spread_ig", 20),
            vix_change_20d=self._change("vix", 20),
            cpi_yoy_change_3m=self._change("cpi_yoy", 90),
            claims_4w_avg=claims_4w_avg,
            claims_change_13w_pct=claims_change_13w_pct,
            rates_as_of=r.get("rates_as_of"),
            credit_as_of=r.get("credit_as_of"),
            inflation_as_of=r.get("inflation_as_of"),
            unemployment_as_of=r.get("unemployment_as_of"),
            claims_as_of=r.get("claims_as_of"),
            volatility_as_of=r.get("volatility_as_of"),
        )


def macro_facts(signal_day: pd.Timestamp) -> dict:
    """Agent-facing entry point: current point-in-time macro facts as a dict."""
    return MacroModel(pd.Timestamp(signal_day)).build_snapshot().to_dict()


