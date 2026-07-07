import numpy as np
import pandas as pd
from dataclasses import dataclass

import database.market.fundamentals_repo as fundamentals_repo
import database.market.tickers_repo as tickers_repo
from data.signals._common import (
    positive_inverse,
    positive_ratio,
    rank_within_sector,
    safe_div,
    safe_growth,
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

GROWTH_COLUMNS = (
    "revenue_growth_yoy",
    "eps_growth_yoy",
    "grossmargin_change_yoy",
    "opinc_growth_yoy",
)

QUALITY_HISTORY_TARGET_YEARS = 5
MAX_HISTORY_OBSERVATION_DISTANCE_DAYS = 183
MIN_QUALITY_HISTORY_YEARS = 4.75
MIN_QUALITY_HISTORY_OBSERVATIONS = 6


def calculate_growth(arq: pd.DataFrame) -> pd.DataFrame:
    """Calculate latest year-over-year growth from quarterly fundamentals."""
    rows = []
    for ticker, group in arq.groupby("ticker"):
        group = group.sort_values("datekey")
        if len(group) < 5:
            continue

        latest = group.iloc[-1]
        prior = group.iloc[-5]
        rows.append(
            {
                "ticker": ticker,
                "revenue_growth_yoy": safe_growth(latest["revenue"], prior["revenue"]),
                "eps_growth_yoy": safe_growth(latest["eps"], prior["eps"]),
                "grossmargin_change_yoy": (
                    latest["grossmargin"] - prior["grossmargin"]
                    if pd.notna(latest["grossmargin"])
                    and pd.notna(prior["grossmargin"])
                    else np.nan
                ),
                "opinc_growth_yoy": safe_growth(latest["opinc"], prior["opinc"]),
            }
        )

    if not rows:
        return pd.DataFrame(columns=list(GROWTH_COLUMNS))
    return pd.DataFrame(rows).set_index("ticker")


def _history_volatility(
    window: pd.DataFrame, complete_history: bool, column: str
) -> float:
    if not complete_history:
        return np.nan
    values = pd.to_numeric(window[column], errors="coerce").dropna()
    if len(values) < 3:
        return np.nan
    return values.std(ddof=0)


def calculate_history_features(art: pd.DataFrame) -> pd.DataFrame:
    """Calculate five-year changes and stability from annual fundamentals."""
    if art.empty:
        return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))

    art = art.copy()
    art["gross_profitability"] = safe_div(art["gp"], art["assets"])
    art["cfo_to_assets"] = safe_div(art["ncfo"], art["assets"])
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
        targets = [
            latest["calendardate"] - pd.DateOffset(years=years_ago)
            for years_ago in range(QUALITY_HISTORY_TARGET_YEARS + 1)
        ]
        sampled_indices = []
        for target in targets:
            distance = (group["calendardate"] - target).abs()
            closest = distance.idxmin()
            if distance.loc[closest].days <= MAX_HISTORY_OBSERVATION_DISTANCE_DAYS:
                sampled_indices.append(closest)

        window = (
            group.loc[list(dict.fromkeys(sampled_indices))]
            .sort_values("calendardate")
            .copy()
        )
        prior = window.iloc[0] if not window.empty else None
        observations = len(window)
        history_years = np.nan
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
                "roa_change_5y": _history_change(
                    latest, prior, complete_history, "roa"
                ),
                "roic_change_5y": _history_change(
                    latest, prior, complete_history, "roic"
                ),
                "cfo_to_assets_change_5y": _history_change(
                    latest, prior, complete_history, "cfo_to_assets"
                ),
                "grossmargin_change_5y": _history_change(
                    latest, prior, complete_history, "grossmargin"
                ),
                "share_dilution_5y": (
                    safe_growth(latest["shareswa"], prior["shareswa"])
                    if prior is not None and complete_history
                    else np.nan
                ),
                "de_change_5y": _history_change(latest, prior, complete_history, "de"),
                "roe_volatility_5y": _history_volatility(
                    window, complete_history, "roe"
                ),
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


def calculate_value(universe: pd.DataFrame) -> pd.DataFrame:
    """Calculate valuation yields and their sector-relative composite."""
    universe = universe.copy()
    universe["earnings_yield"] = positive_inverse(universe["pe"])
    universe["fcf_yield"] = positive_ratio(universe["fcf"], universe["marketcap"])
    universe["ebitda_yield"] = positive_inverse(universe["evebitda"])
    universe["book_yield"] = positive_inverse(universe["pb"])
    universe["sales_yield"] = positive_inverse(universe["ps"])

    percentile_columns = []
    for column in VALUE_YIELD_COLUMNS:
        percentile = f"{column}_percentile"
        universe[percentile] = rank_within_sector(universe[column], universe["sector"])
        percentile_columns.append(percentile)

    universe["valid_value_metrics"] = (
        universe[list(VALUE_YIELD_COLUMNS)].notna().sum(axis=1)
    )
    universe["value_composite_score"] = universe[percentile_columns].mean(
        axis=1, skipna=True
    )
    universe.loc[universe["valid_value_metrics"] < 2, "value_composite_score"] = np.nan
    universe["value_composite_percentile"] = rank_within_sector(
        universe["value_composite_score"], universe["sector"]
    )
    return universe


def _mean_with_minimum(
    frame: pd.DataFrame, columns: list[str], minimum: int
) -> tuple[pd.Series, pd.Series]:
    valid_count = frame[columns].notna().sum(axis=1)
    score = frame[columns].mean(axis=1, skipna=True)
    return score.where(valid_count >= minimum), valid_count


def calculate_quality(universe: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Calculate quality pillars and their sector-relative composite."""
    universe = universe.join(history, how="left")
    universe["interest_coverage"] = safe_div(universe["ebit"], universe["intexp"])
    universe["gross_profitability"] = safe_div(universe["gp"], universe["assets"])
    universe["cfo_to_assets"] = safe_div(universe["ncfo"], universe["assets"])
    universe["accrual_quality"] = safe_div(
        universe["ncfo"] - universe["netinc"], universe["assets"]
    )
    payout = universe[["ncfcommon", "ncfdiv"]].sum(axis=1, min_count=1)
    universe["net_payout_yield"] = safe_div(
        -payout, universe["marketcap"].where(universe["marketcap"] > 0)
    )

    universe["roe_percentile"] = universe["roe"].rank(pct=True, method="average") * 100
    universe["de_percentile"] = rank_within_sector(universe["de"], universe["sector"])
    universe["currentratio_percentile"] = rank_within_sector(
        universe["currentratio"], universe["sector"]
    )

    pillar_columns = []
    for pillar, metrics in QUALITY_PILLAR_METRICS.items():
        metric_percentiles = []
        for metric, direction in metrics.items():
            percentile = f"_quality_{metric}_percentile"
            values = universe.get(
                metric, pd.Series(np.nan, index=universe.index, dtype=float)
            )
            universe[percentile] = rank_within_sector(
                values * direction, universe["sector"]
            )
            metric_percentiles.append(percentile)

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
    required = [
        "quality_profitability_score",
        "quality_growth_score",
        "quality_safety_score",
    ]
    universe.loc[universe[required].isna().any(axis=1), "quality_composite_score"] = (
        np.nan
    )
    universe["quality_composite_percentile"] = rank_within_sector(
        universe["quality_composite_score"], universe["sector"]
    )
    return universe


def _attach_sectors(universe: pd.DataFrame) -> pd.DataFrame:
    universe = universe.copy()
    if universe.empty:
        universe["sector"] = pd.Series(dtype="object")
        return universe

    metadata = tickers_repo.get(
        tickers=universe.index.astype(str).tolist(),
        table_code="SEP",
    )
    sectors = metadata.drop_duplicates("ticker", keep="last").set_index("ticker")[
        "sector"
    ]
    universe["sector"] = sectors.reindex(universe.index).fillna("Unknown")
    return universe


def build_fundamental_signals(
    tickers: list[str] | None, signal_day: pd.Timestamp
) -> pd.DataFrame:
    """Build point-in-time growth, value, and quality signals."""
    signal_day = pd.Timestamp(signal_day)
    universe = fundamentals_repo.get_latest_rows(None, "ART", signal_day)
    if universe.empty:
        return pd.DataFrame()

    universe = _attach_sectors(universe.set_index("ticker"))

    history_start = signal_day - pd.DateOffset(years=6)
    art_history = fundamentals_repo.get(
        tickers=None,
        dimension="ART",
        start_date=str(history_start.date()),
        end_date=str(signal_day.date()),
    )
    art_history = art_history[pd.to_datetime(art_history["datekey"]) <= signal_day]
    history = calculate_history_features(art_history)

    universe = calculate_value(universe)
    universe = calculate_quality(universe, history)

    growth_start = signal_day - pd.Timedelta(days=730)
    arq = fundamentals_repo.get(
        tickers=universe.index.astype(str).tolist(),
        dimension="ARQ",
        start_date=str(growth_start.date()),
        end_date=str(signal_day.date()),
    )
    arq = arq[pd.to_datetime(arq["datekey"]) <= signal_day]
    growth = calculate_growth(arq)
    growth["revenue_growth_percentile"] = (
        growth["revenue_growth_yoy"].rank(pct=True) * 100
    )
    universe = universe.join(growth, how="left")

    if tickers is None:
        return universe
    present = [ticker for ticker in tickers if ticker in universe.index]
    return universe.loc[present]


@dataclass
class FundamentalsSnapshot:
    ticker: str
    signal_day: pd.Timestamp

    sector: str
    marketcap: float

    earnings_yield: float
    fcf_yield: float
    ebitda_yield: float
    book_yield: float
    sales_yield: float
    valid_value_metrics: int
    value_composite_score: float
    value_composite_percentile: float

    quality_profitability_score: float
    quality_growth_score: float
    quality_safety_score: float
    quality_capital_discipline_score: float
    valid_quality_pillars: int
    quality_composite_score: float
    quality_composite_percentile: float

    roe: float
    roa: float
    roic: float
    de: float
    currentratio: float
    roe_percentile: float
    de_percentile: float
    currentratio_percentile: float

    ncfo: float
    fcf: float
    netinc: float
    netmargin: float
    grossmargin: float
    gross_profitability: float
    cfo_to_assets: float
    accrual_quality: float
    interest_coverage: float
    net_payout_yield: float
    divyield: float

    revenue_growth_yoy: float
    eps_growth_yoy: float
    grossmargin_change_yoy: float
    opinc_growth_yoy: float
    revenue_growth_percentile: float

    gross_profitability_change_5y: float
    roa_change_5y: float
    roic_change_5y: float
    cfo_to_assets_change_5y: float
    grossmargin_change_5y: float
    share_dilution_5y: float
    de_change_5y: float
    roe_volatility_5y: float
    grossmargin_volatility_5y: float
    quality_history_years: float
    quality_history_observations: int
    complete_multi_year_history: bool

    def risk_flags(self) -> dict[str, bool]:
        return fundamental_risk_flags(self)


class FundamentalsModel:
    def __init__(self, signal_day: pd.Timestamp, tickers: list[str] | None):
        self.signal_day = pd.Timestamp(signal_day)
        self.tickers = tickers
        self.data = None
        self.load_data()

    def load_data(self) -> None:
        self.data = build_fundamental_signals(self.tickers, self.signal_day)

    def get(self, ticker: str, col: str):
        if ticker not in self.data.index:
            raise ValueError(f"Ticker {ticker} not in fundamentals data")
        if col not in self.data.columns:
            raise ValueError(f"Column {col} not in fundamentals data")
        return self.data.loc[ticker, col]

    def build_snapshot(self, ticker: str) -> FundamentalsSnapshot:
        if ticker not in self.data.index:
            raise ValueError(f"Ticker {ticker} not in fundamentals data")
        row = self.data.loc[ticker]
        return FundamentalsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            sector=row["sector"],
            marketcap=row["marketcap"],
            earnings_yield=row["earnings_yield"],
            fcf_yield=row["fcf_yield"],
            ebitda_yield=row["ebitda_yield"],
            book_yield=row["book_yield"],
            sales_yield=row["sales_yield"],
            valid_value_metrics=row["valid_value_metrics"],
            value_composite_score=row["value_composite_score"],
            value_composite_percentile=row["value_composite_percentile"],
            quality_profitability_score=row["quality_profitability_score"],
            quality_growth_score=row["quality_growth_score"],
            quality_safety_score=row["quality_safety_score"],
            quality_capital_discipline_score=row[
                "quality_capital_discipline_score"
            ],
            valid_quality_pillars=row["valid_quality_pillars"],
            quality_composite_score=row["quality_composite_score"],
            quality_composite_percentile=row["quality_composite_percentile"],
            roe=row["roe"],
            roa=row["roa"],
            roic=row["roic"],
            de=row["de"],
            currentratio=row["currentratio"],
            roe_percentile=row["roe_percentile"],
            de_percentile=row["de_percentile"],
            currentratio_percentile=row["currentratio_percentile"],
            ncfo=row["ncfo"],
            fcf=row["fcf"],
            netinc=row["netinc"],
            netmargin=row["netmargin"],
            grossmargin=row["grossmargin"],
            gross_profitability=row["gross_profitability"],
            cfo_to_assets=row["cfo_to_assets"],
            accrual_quality=row["accrual_quality"],
            interest_coverage=row["interest_coverage"],
            net_payout_yield=row["net_payout_yield"],
            divyield=row["divyield"],
            revenue_growth_yoy=row["revenue_growth_yoy"],
            eps_growth_yoy=row["eps_growth_yoy"],
            grossmargin_change_yoy=row["grossmargin_change_yoy"],
            opinc_growth_yoy=row["opinc_growth_yoy"],
            revenue_growth_percentile=row["revenue_growth_percentile"],
            gross_profitability_change_5y=row["gross_profitability_change_5y"],
            roa_change_5y=row["roa_change_5y"],
            roic_change_5y=row["roic_change_5y"],
            cfo_to_assets_change_5y=row["cfo_to_assets_change_5y"],
            grossmargin_change_5y=row["grossmargin_change_5y"],
            share_dilution_5y=row["share_dilution_5y"],
            de_change_5y=row["de_change_5y"],
            roe_volatility_5y=row["roe_volatility_5y"],
            grossmargin_volatility_5y=row["grossmargin_volatility_5y"],
            quality_history_years=row["quality_history_years"],
            quality_history_observations=row["quality_history_observations"],
            complete_multi_year_history=row["complete_multi_year_history"],
        )


def fundamental_risk_flags(snap: FundamentalsSnapshot) -> dict[str, bool]:
    """Return the fundamental risk gates consumed by the strategies."""
    return {
        "high_leverage": snap.de > 2.0,
        "negative_fcf": snap.fcf < 0,
        "losing_money": snap.netmargin < 0,
        "revenue_declining": snap.revenue_growth_yoy < -0.05,
        "eps_declining": snap.eps_growth_yoy < -0.10,
        "interest_at_risk": 0 < snap.interest_coverage < 1.5,
        "extreme_sector_leverage": snap.de_percentile >= 90,
        "weak_sector_liquidity": snap.currentratio_percentile < 10,
        "negative_ocf": snap.ncfo < 0,
        "cash_burn": snap.ncfo < 0 and snap.fcf < 0,
        "combined_deterioration": (
            snap.revenue_growth_yoy < -0.10
            and snap.grossmargin_change_yoy < 0
            and snap.opinc_growth_yoy < 0
        ),
    }
