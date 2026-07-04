import pandas as pd
import numpy as np
from dataclasses import dataclass, fields
from typing import Literal

import database.market.macro_repo as macro_repo


def _python_scalar(v):
    if isinstance(v, np.generic):
        return v.item()
    return v


def _is_known(value) -> bool:
    return value is not None and not pd.isna(value)


@dataclass(frozen=True)
class MacroOverlay:
    regime: Literal["supportive", "mixed", "hostile"]
    hard_veto: bool
    drivers: tuple[str, ...]
    hazards: tuple[str, ...]
    as_of: dict[str, str | None]

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "hard_veto": self.hard_veto,
            "drivers": list(self.drivers),
            "hazards": list(self.hazards),
            "as_of": self.as_of,
        }


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

    def overlay(self) -> MacroOverlay:
        """Classify broad financial conditions without a false-precision score."""
        drivers: list[str] = []
        hazards: list[str] = []

        if (
            _is_known(self.spread_hy)
            and _is_known(self.spread_hy_change_20d)
            and self.spread_hy < 4.0
            and self.spread_hy_change_20d <= 0
        ):
            drivers.append("benign_credit")
        if (
            _is_known(self.vix)
            and _is_known(self.vix_change_20d)
            and self.vix < 25
            and self.vix_change_20d <= 0
        ):
            drivers.append("contained_volatility")
        if (
            _is_known(self.real_yield_change_20d)
            and self.real_yield_change_20d < 0.25
        ):
            drivers.append("stable_real_yields")
        if (
            _is_known(self.claims_change_13w_pct)
            and self.claims_change_13w_pct < 0.10
        ):
            drivers.append("stable_labor")

        if _is_known(self.spread_hy) and self.spread_hy > 6.0:
            hazards.append("credit_stress")
        if (
            _is_known(self.spread_hy_change_20d)
            and self.spread_hy_change_20d > 0.75
        ):
            hazards.append("credit_widening_fast")
        if _is_known(self.vix) and self.vix >= 30:
            hazards.append("high_volatility")
        if _is_known(self.vix_change_20d) and self.vix_change_20d > 7.5:
            hazards.append("volatility_spike")
        if (
            _is_known(self.real_yield_change_20d)
            and self.real_yield_change_20d > 0.50
        ):
            hazards.append("real_yield_shock")
        if (
            _is_known(self.claims_change_13w_pct)
            and self.claims_change_13w_pct > 0.15
        ):
            hazards.append("claims_accelerating")

        hard_veto = (
            (_is_known(self.vix) and self.vix >= 40)
            or (_is_known(self.spread_hy) and self.spread_hy >= 8.0)
            or ("credit_stress" in hazards and "high_volatility" in hazards)
        )
        if (
            hard_veto
            or "credit_stress" in hazards
            or "high_volatility" in hazards
            or len(hazards) >= 2
        ):
            regime = "hostile"
        elif not hazards and len(drivers) >= 3:
            regime = "supportive"
        else:
            regime = "mixed"

        return MacroOverlay(
            regime=regime,
            hard_veto=hard_veto,
            drivers=tuple(drivers),
            hazards=tuple(hazards),
            as_of=self.as_of_dates(),
        )


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


def print_snapshot_report(snap: MacroSnapshot) -> None:
    print(f"\n=== Macro | {snap.signal_day.date()} ===")
    print(
        f"  Yield curve 2-10: {snap.yield_curve_2_10:+.2f}  |  10y: {snap.yield_10y:.2f}%  |  FFR: {snap.fed_funds_rate:.2f}%"
    )
    print(
        f"  Real yield 10y: {snap.real_yield_10y:.2f}%  |  Breakeven 10y: {snap.breakeven_10y:.2f}%"
    )
    print(
        f"  HY spread: {snap.spread_hy:.2f}% ({snap.spread_hy_change_20d:+.2f} 20d)"
        f"  |  IG spread: {snap.spread_ig:.2f}% ({snap.spread_ig_change_20d:+.2f} 20d)"
    )
    print(f"  CPI YoY: {snap.cpi_yoy:.2f}%  |  Core CPI YoY: {snap.cpi_core_yoy:.2f}%")
    print(
        f"  Unemployment: {snap.unemployment_rate:.1f}%  |  Jobless claims: {snap.jobless_claims:,.0f}"
    )
    print(f"  VIX: {snap.vix:.1f}  |  DXY: {snap.dxy:.1f}  |  WTI: ${snap.oil_wti:.1f}")
    print(f"  Overlay:     {snap.overlay().to_dict()}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2026-06-20")
    model = MacroModel(signal_day=signal_day)
    print_snapshot_report(model.build_snapshot())
