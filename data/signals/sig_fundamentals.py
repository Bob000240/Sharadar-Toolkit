import pandas as pd
from dataclasses import dataclass, fields
import numpy as np
import database.market.fundamentals_repo as fundamentals_repo
import database.market.tickers_repo as tickers_repo
from data.signals._common import (
    python_scalar as _python_scalar,
    safe_div,
    safe_growth as _safe_growth,
    positive_inverse as _positive_inverse,
    positive_ratio as _positive_ratio,
    rank_within_sector as _rank_within_sector,
)


VALUE_YIELD_COLUMNS = (
    "earnings_yield",
    "fcf_yield",
    "ebitda_yield",
    "book_yield",
    "sales_yield",
)
QUALITY_PILLAR_METRICS = {
    "profitability": {
        "gross_profitability": 1,
        "roa": 1,
        "roic": 1,
        "cfo_to_assets": 1,
        "grossmargin": 1,
        "accrual_quality": 1,
    },
    "growth": {
        "gross_profitability_change_5y": 1,
        "roa_change_5y": 1,
        "roic_change_5y": 1,
        "cfo_to_assets_change_5y": 1,
        "grossmargin_change_5y": 1,
    },
    "safety": {
        "de": -1,
        "currentratio": 1,
        "interest_coverage": 1,
        "roe_volatility_5y": -1,
        "grossmargin_volatility_5y": -1,
        "de_change_5y": -1,
    },
    "capital_discipline": {
        "net_payout_yield": 1,
        "share_dilution_5y": -1,
    },
}
# Minimum valid metrics per pillar to score it (out of 6/5/6/2 metrics respectively
# — see QUALITY_PILLAR_METRICS above). CALIBRATION: counts are not independently
# justified beyond "a majority of the pillar's metrics must be present."
QUALITY_PILLAR_MINIMUMS = {
    "profitability": 3,
    "growth": 2,
    "safety": 3,
    "capital_discipline": 1,
}
QUALITY_HISTORY_COLUMNS = (
    "gross_profitability_change_5y",
    "roa_change_5y",
    "roic_change_5y",
    "cfo_to_assets_change_5y",
    "grossmargin_change_5y",
    "share_dilution_5y",
    "de_change_5y",
    "roe_volatility_5y",
    "grossmargin_volatility_5y",
    "quality_history_years",
    "quality_history_observations",
    "complete_multi_year_history",
)
# 5-year lookback for quality's growth pillar (Piotroski 2000 uses 1-year changes;
# this is a deliberate deviation toward durable multi-year improvement, not a
# reproduction of Piotroski's exact window). CALIBRATION: 5y vs. e.g. 3y is a
# modeling choice, not independently derived.
QUALITY_HISTORY_TARGET_YEARS = 5
# Tolerance for matching a "N years ago" target date to an actual filing date.
# CALIBRATION: uncited, picked as roughly half a year of slack.
MAX_HISTORY_OBSERVATION_DISTANCE_DAYS = 183
# Minimum span/count of annual observations to trust a 5y-change measurement.
# CALIBRATION: uncited magnitude bands.
MIN_QUALITY_HISTORY_YEARS = 4.75
MIN_QUALITY_HISTORY_OBSERVATIONS = 6


# Pure column helpers (python_scalar, safe_div, safe_growth, positive_inverse,
# positive_ratio, rank_within_sector) live in data.signals._common, imported above.


def _mean_with_minimum(
    frame: pd.DataFrame,
    columns: list[str],
    minimum: int,
) -> tuple[pd.Series, pd.Series]:
    valid_count = frame[columns].notna().sum(axis=1)
    score = frame[columns].mean(axis=1, skipna=True)
    return score.where(valid_count >= minimum), valid_count


# ── Column-derivation helpers (all feature creation lives here) ──────────────


def _compute_growth(arq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tkr, grp in arq.groupby("ticker"):
        grp = grp.sort_values("datekey")
        if len(grp) < 5:
            rows.append(
                {
                    "ticker": tkr,
                    "revenue_growth_yoy": float("nan"),
                    "eps_growth_yoy": float("nan"),
                    "grossmargin_change_yoy": float("nan"),
                    "opinc_growth_yoy": float("nan"),
                }
            )
            continue
        latest = grp.iloc[-1]
        prior = grp.iloc[-5]

        rows.append(
            {
                "ticker": tkr,
                "revenue_growth_yoy": _safe_growth(latest["revenue"], prior["revenue"]),
                "eps_growth_yoy": _safe_growth(latest["eps"], prior["eps"]),
                "grossmargin_change_yoy": (
                    latest["grossmargin"] - prior["grossmargin"]
                    if pd.notna(latest["grossmargin"]) and pd.notna(prior["grossmargin"])
                    else float("nan")
                ),
                "opinc_growth_yoy": _safe_growth(latest["opinc"], prior["opinc"]),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "revenue_growth_yoy",
                "eps_growth_yoy",
                "grossmargin_change_yoy",
                "opinc_growth_yoy",
            ]
        )
    return pd.DataFrame(rows).set_index("ticker")


def _compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    df["interest_coverage"] = safe_div(df["ebit"], df["intexp"])
    # Only meaningful when OCF is positive; negative OCF makes ratio negative/misleading
    df["capex_to_ocf"] = safe_div(df["capex"].abs(), df["ncfo"].where(df["ncfo"] > 0))
    df["rnd_intensity"] = safe_div(df["rnd"], df["revenue"])
    df["gross_profitability"] = safe_div(df["gp"], df["assets"])
    df["cfo_to_assets"] = safe_div(df["ncfo"], df["assets"])
    df["accrual_quality"] = safe_div(df["ncfo"] - df["netinc"], df["assets"])
    payout = df[["ncfcommon", "ncfdiv"]].sum(axis=1, min_count=1)
    df["net_payout_yield"] = safe_div(-payout, df["marketcap"].where(df["marketcap"] > 0))
    df["earnings_yield"] = _positive_inverse(df["pe"])
    df["fcf_yield"] = _positive_ratio(df["fcf"], df["marketcap"])
    df["ebitda_yield"] = _positive_inverse(df["evebitda"])
    df["book_yield"] = _positive_inverse(df["pb"])
    df["sales_yield"] = _positive_inverse(df["ps"])
    return df


def _history_change(latest, prior, complete_history, column) -> float:
    if prior is None or not complete_history:
        return float("nan")
    now, then = latest[column], prior[column]
    if pd.isna(now) or pd.isna(then):
        return float("nan")
    return now - then


def _history_volatility(window, complete_history, column) -> float:
    if not complete_history:
        return float("nan")
    values = pd.to_numeric(window[column], errors="coerce").dropna()
    if len(values) < 3:
        return float("nan")
    return values.std(ddof=0)


def _compute_quality_history(art: pd.DataFrame) -> pd.DataFrame:
    if art.empty:
        return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))

    art = _compute_derived(art.copy())
    art["calendardate"] = pd.to_datetime(art["calendardate"])
    art["datekey"] = pd.to_datetime(art["datekey"])
    rows = []

    for ticker, group in art.groupby("ticker"):
        group = (
            group.dropna(subset=["calendardate"])
            .sort_values(["calendardate", "datekey"])
            .drop_duplicates("calendardate", keep="last")
        )
        if group.empty:
            continue

        latest = group.iloc[-1]
        target_dates = [
            latest["calendardate"] - pd.DateOffset(years=years_ago)
            for years_ago in range(QUALITY_HISTORY_TARGET_YEARS + 1)
        ]
        sampled_indices = []
        for target_date in target_dates:
            distance = (group["calendardate"] - target_date).abs()
            closest_index = distance.idxmin()
            if distance.loc[closest_index].days <= MAX_HISTORY_OBSERVATION_DISTANCE_DAYS:
                sampled_indices.append(closest_index)

        window = (
            group.loc[list(dict.fromkeys(sampled_indices))]
            .sort_values("calendardate")
            .copy()
        )
        prior = window.iloc[0] if not window.empty else None

        history_years = float("nan")
        observations = len(window)
        if prior is not None:
            history_years = (
                latest["calendardate"] - prior["calendardate"]
            ).days / 365.25

        complete_history = (
            history_years >= MIN_QUALITY_HISTORY_YEARS
            and observations >= MIN_QUALITY_HISTORY_OBSERVATIONS
        )

        rows.append(
            {
                "ticker": ticker,
                "gross_profitability_change_5y": _history_change(
                    latest, prior, complete_history, "gross_profitability"
                ),
                "roa_change_5y": _history_change(latest, prior, complete_history, "roa"),
                "roic_change_5y": _history_change(latest, prior, complete_history, "roic"),
                "cfo_to_assets_change_5y": _history_change(
                    latest, prior, complete_history, "cfo_to_assets"
                ),
                "grossmargin_change_5y": _history_change(
                    latest, prior, complete_history, "grossmargin"
                ),
                "share_dilution_5y": (
                    _safe_growth(latest["shareswa"], prior["shareswa"])
                    if prior is not None and complete_history
                    else float("nan")
                ),
                "de_change_5y": _history_change(latest, prior, complete_history, "de"),
                "roe_volatility_5y": _history_volatility(window, complete_history, "roe"),
                "grossmargin_volatility_5y": _history_volatility(
                    window, complete_history, "grossmargin"
                ),
                "quality_history_years": history_years,
                "quality_history_observations": observations,
                "complete_multi_year_history": complete_history,
            }
        )

    if not rows:
        return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))
    return pd.DataFrame(rows).set_index("ticker")


def _attach_sectors(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        df["sector"] = pd.Series(dtype="object")
        return df

    metadata = tickers_repo.get(
        tickers=df.index.astype(str).tolist(),
        table_code="SEP",
    )
    sectors = metadata.drop_duplicates("ticker", keep="last").set_index("ticker")[
        "sector"
    ]
    df["sector"] = sectors.reindex(df.index).fillna("Unknown")
    return df


def _compute_cross_section(universe: pd.DataFrame) -> pd.DataFrame:
    universe = _attach_sectors(universe)

    universe["roe_percentile"] = universe["roe"].rank(pct=True, method="average") * 100
    universe["de_percentile"] = _rank_within_sector(universe["de"], universe["sector"])
    universe["currentratio_percentile"] = _rank_within_sector(
        universe["currentratio"], universe["sector"]
    )

    percentile_columns = []
    for value_column in VALUE_YIELD_COLUMNS:
        percentile_column = f"{value_column}_percentile"
        universe[percentile_column] = _rank_within_sector(
            universe[value_column], universe["sector"]
        )
        percentile_columns.append(percentile_column)

    universe["valid_value_metrics"] = (
        universe[list(VALUE_YIELD_COLUMNS)].notna().sum(axis=1)
    )
    universe["value_composite_score"] = universe[percentile_columns].mean(
        axis=1, skipna=True
    )
    universe.loc[universe["valid_value_metrics"] < 2, "value_composite_score"] = np.nan
    universe["value_composite_percentile"] = _rank_within_sector(
        universe["value_composite_score"], universe["sector"]
    )

    pillar_columns = []
    for pillar, metrics in QUALITY_PILLAR_METRICS.items():
        metric_percentiles = []
        for metric, direction in metrics.items():
            percentile_column = f"_quality_{metric}_percentile"
            values = universe.get(
                metric, pd.Series(np.nan, index=universe.index, dtype=float)
            )
            universe[percentile_column] = _rank_within_sector(
                values * direction, universe["sector"]
            )
            metric_percentiles.append(percentile_column)

        score_column = f"quality_{pillar}_score"
        count_column = f"_valid_quality_{pillar}_metrics"
        universe[score_column], universe[count_column] = _mean_with_minimum(
            universe, metric_percentiles, QUALITY_PILLAR_MINIMUMS[pillar]
        )
        pillar_columns.append(score_column)

    universe["valid_quality_pillars"] = universe[pillar_columns].notna().sum(axis=1)
    universe["quality_composite_score"] = universe[pillar_columns].mean(
        axis=1, skipna=True
    )
    required_pillars = [
        "quality_profitability_score",
        "quality_growth_score",
        "quality_safety_score",
    ]
    universe.loc[
        universe[required_pillars].isna().any(axis=1), "quality_composite_score"
    ] = np.nan
    universe["quality_composite_percentile"] = _rank_within_sector(
        universe["quality_composite_score"], universe["sector"]
    )
    return universe


@dataclass
class FundamentalsSnapshot:
    """Per-ticker view onto the fundamentals pipeline. Only carries fields read
    by valuation()/profitability()/balance_sheet_health()/risk_flags() or by a
    strategy directly — the underlying compute pipeline (_compute_derived,
    _compute_cross_section, _compute_quality_history) still computes and uses
    many more intermediate columns; this snapshot just doesn't re-expose them."""

    ticker: str
    signal_day: pd.Timestamp
    datekey: pd.Timestamp
    calendardate: pd.Timestamp
    sector: str

    # Valuation (ART — trailing twelve months)
    pe: float
    pb: float
    ps: float
    evebitda: float
    divyield: float
    marketcap: float

    # Comparable valuation yields; invalid or non-positive bases are NaN.
    earnings_yield: float
    fcf_yield: float

    # Profitability (ART)
    roe: float
    roa: float
    roic: float
    grossmargin: float
    netmargin: float
    fcf: float
    opinc: float
    accrual_quality: float

    # Earnings quality (ART)
    ncfo: float
    interest_coverage: float  # ebit / intexp

    # Balance sheet (ART)
    de: float
    currentratio: float
    cashneq: float
    workingcapital: float
    payoutratio: float

    # Growth (YoY from ARQ: most recent quarter vs same quarter 1 year prior)
    revenue_growth_yoy: float
    eps_growth_yoy: float
    grossmargin_change_yoy: float
    opinc_growth_yoy: float

    # Cross-sectional percentiles / composites
    roe_percentile: float
    value_composite_percentile: float
    valid_value_metrics: int
    de_percentile: float
    currentratio_percentile: float
    quality_profitability_score: float
    quality_safety_score: float
    quality_composite_score: float
    quality_composite_percentile: float
    valid_quality_pillars: int

    def __post_init__(self) -> None:
        for field in fields(self):
            setattr(self, field.name, _python_scalar(getattr(self, field.name)))

    def valuation(self) -> dict[str, bool]:
        return {
            "pe_reasonable": 0 < self.pe < 30,
            "pb_reasonable": 0 < self.pb < 5,
            "ps_reasonable": 0 < self.ps < 5,
            "evebitda_reasonable": 0 < self.evebitda < 20,
            "pays_dividend": self.divyield > 0,
            "large_cap": self.marketcap >= 10_000_000_000,
            "mid_cap": 1_000_000_000 <= self.marketcap < 10_000_000_000,
            "enough_value_metrics": self.valid_value_metrics >= 2,
            "sector_deep_value": self.value_composite_percentile >= 70,
        }

    def profitability(self) -> dict[str, bool]:
        return {
            "roe_positive": self.roe > 0,
            "roe_strong": self.roe > 0.15,
            "roa_positive": self.roa > 0,
            "roic_positive": self.roic > 0,
            "gross_margin_ok": self.grossmargin > 0.20,
            "net_margin_pos": self.netmargin > 0,
            "fcf_positive": self.fcf > 0,
            "opinc_positive": self.opinc > 0,
        }

    def balance_sheet_health(self) -> dict[str, bool]:
        return {
            "low_leverage": self.de < 1.0,
            "current_ratio_ok": self.currentratio > 1.5,
            "has_cash": self.cashneq > 0,
            "positive_working_cap": self.workingcapital > 0,
            "sustainable_payout": 0 <= self.payoutratio < 0.75,
        }

    def risk_flags(self) -> dict[str, bool]:
        return {
            "high_leverage": self.de > 2.0,
            "negative_fcf": self.fcf < 0,
            "losing_money": self.netmargin < 0,
            "revenue_declining": self.revenue_growth_yoy < -0.05,
            "eps_declining": self.eps_growth_yoy < -0.10,
            "interest_at_risk": 0 < self.interest_coverage < 1.5,
            "extreme_sector_leverage": self.de_percentile >= 90,
            "weak_sector_liquidity": self.currentratio_percentile < 10,
            "negative_ocf": self.ncfo < 0,
            "cash_burn": self.ncfo < 0 and self.fcf < 0,
            "combined_deterioration": (
                self.revenue_growth_yoy < -0.10
                and self.grossmargin_change_yoy < 0
                and self.opinc_growth_yoy < 0
            ),
        }


class FundamentalsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        tickers: list[str],
    ):
        self.signal_day = signal_day
        self.tickers = tickers
        self.data = None
        self.load_data()

    def _load_arq(self, tickers: list[str] | None) -> pd.DataFrame:
        lookback = self.signal_day - pd.Timedelta(days=730)
        arq = fundamentals_repo.get(
            tickers=tickers,
            dimension="ARQ",
            start_date=str(lookback.date()),
            end_date=str(self.signal_day.date()),
        )
        return arq[pd.to_datetime(arq["datekey"]) <= self.signal_day]

    def _load_art_history(self) -> pd.DataFrame:
        lookback = self.signal_day - pd.DateOffset(years=6)
        art = fundamentals_repo.get(
            tickers=None,
            dimension="ART",
            start_date=str(lookback.date()),
            end_date=str(self.signal_day.date()),
        )
        return art[pd.to_datetime(art["datekey"]) <= self.signal_day]

    def load_data(self) -> None:
        art = fundamentals_repo.get_latest(self.tickers, "ART", self.signal_day)
        art = art.set_index("ticker")
        art = _compute_derived(art)

        # Cross-sectional ranks use the full ART universe (point-in-time). TICKERS
        # currently stores only current sector classifications; historical sector
        # versioning remains a separate data-model requirement.
        universe = fundamentals_repo.get_latest(None, "ART", self.signal_day)
        universe = universe.set_index("ticker")
        universe = _compute_derived(universe)
        quality_history = _compute_quality_history(self._load_art_history())
        universe = universe.join(quality_history, how="left")
        universe = _compute_cross_section(universe)

        # YoY growth (and its percentile) are computed across the full universe so
        # the percentile is independent of the request batch; the batch's own
        # growth values are a subset of this same computation.
        growth = _compute_growth(self._load_arq(universe.index.tolist()))
        growth["revenue_growth_percentile"] = (
            growth["revenue_growth_yoy"].rank(pct=True) * 100
        )

        self.data = art.join(growth, how="left")
        cross_section_columns = [
            "sector",
            "roe_percentile",
            "de_percentile",
            "currentratio_percentile",
            "earnings_yield_percentile",
            "fcf_yield_percentile",
            "ebitda_yield_percentile",
            "book_yield_percentile",
            "sales_yield_percentile",
            "value_composite_score",
            "value_composite_percentile",
            "valid_value_metrics",
            *QUALITY_HISTORY_COLUMNS,
            "quality_profitability_score",
            "quality_growth_score",
            "quality_safety_score",
            "quality_capital_discipline_score",
            "quality_composite_score",
            "quality_composite_percentile",
            "valid_quality_pillars",
        ]
        for column in cross_section_columns:
            self.data[column] = universe[column].reindex(self.data.index)

    def get(self, ticker: str, col: str):
        if ticker not in self.data.index:
            raise ValueError(f"Ticker {ticker} not in data")
        if col not in self.data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.data.loc[ticker, col]

    def build_snapshot(self, ticker: str) -> FundamentalsSnapshot:
        def g(column: str):
            return self.get(ticker, column)

        return FundamentalsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            datekey=pd.Timestamp(g("datekey")),
            calendardate=pd.Timestamp(g("calendardate")),
            sector=g("sector"),
            pe=g("pe"),
            pb=g("pb"),
            ps=g("ps"),
            evebitda=g("evebitda"),
            divyield=g("divyield"),
            marketcap=g("marketcap"),
            earnings_yield=g("earnings_yield"),
            fcf_yield=g("fcf_yield"),
            roe=g("roe"),
            roa=g("roa"),
            roic=g("roic"),
            grossmargin=g("grossmargin"),
            netmargin=g("netmargin"),
            fcf=g("fcf"),
            opinc=g("opinc"),
            accrual_quality=g("accrual_quality"),
            ncfo=g("ncfo"),
            interest_coverage=g("interest_coverage"),
            de=g("de"),
            currentratio=g("currentratio"),
            cashneq=g("cashneq"),
            workingcapital=g("workingcapital"),
            payoutratio=g("payoutratio"),
            revenue_growth_yoy=g("revenue_growth_yoy"),
            eps_growth_yoy=g("eps_growth_yoy"),
            grossmargin_change_yoy=g("grossmargin_change_yoy"),
            opinc_growth_yoy=g("opinc_growth_yoy"),
            roe_percentile=g("roe_percentile"),
            value_composite_percentile=g("value_composite_percentile"),
            valid_value_metrics=g("valid_value_metrics"),
            de_percentile=g("de_percentile"),
            currentratio_percentile=g("currentratio_percentile"),
            quality_profitability_score=g("quality_profitability_score"),
            quality_safety_score=g("quality_safety_score"),
            quality_composite_score=g("quality_composite_score"),
            quality_composite_percentile=g("quality_composite_percentile"),
            valid_quality_pillars=g("valid_quality_pillars"),
        )


def print_snapshot_report(snap: FundamentalsSnapshot) -> None:
    sections = {
        "Valuation": snap.valuation(),
        "Profitability": snap.profitability(),
        "Balance Sheet": snap.balance_sheet_health(),
        "Risk Flags": snap.risk_flags(),
    }
    print(
        f"\n=== {snap.ticker} | {snap.signal_day.date()} (period {snap.calendardate.date()}, filed {snap.datekey.date()}) ==="
    )
    print(
        f"value_pctile={snap.value_composite_percentile:.1f}  "
        f"quality_pctile={snap.quality_composite_percentile:.1f}  "
        f"valid_pillars={snap.valid_quality_pillars}"
    )
    for title, values in sections.items():
        print(f"{title}: {values}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2024-06-30")
    tickers = ["AAPL", "MSFT", "GOOGL"]

    model = FundamentalsModel(signal_day=signal_day, tickers=tickers)
    for tkr in tickers:
        print_snapshot_report(model.build_snapshot(tkr))
