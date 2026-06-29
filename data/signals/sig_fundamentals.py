import pandas as pd
from dataclasses import dataclass, fields
import numpy as np
import database.market.fundamentals_repo as fundamentals_repo
import database.market.tickers_repo as tickers_repo


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
MIN_SECTOR_RANK_SIZE = 5
QUALITY_HISTORY_TARGET_YEARS = 5
MAX_HISTORY_OBSERVATION_DISTANCE_DAYS = 183
MIN_QUALITY_HISTORY_YEARS = 4.75
MIN_QUALITY_HISTORY_OBSERVATIONS = 6


def _python_scalar(value):
    if isinstance(value, np.generic):
        return value.item()
    return value


def _safe_growth(now, then) -> float:
    if pd.isna(now) or pd.isna(then) or then == 0:
        return float("nan")
    return (now - then) / abs(then)


def _positive_inverse(values: pd.Series) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.notna() & np.isfinite(values) & (values > 0)
    result.loc[valid] = 1.0 / values.loc[valid]
    return result


def _positive_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
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


def _rank_within_sector(
    values: pd.Series,
    sectors: pd.Series,
    min_sector_size: int = MIN_SECTOR_RANK_SIZE,
) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    sectors = sectors.fillna("Unknown")
    sector_rank = values.groupby(sectors).rank(pct=True, method="average") * 100
    sector_count = values.notna().groupby(sectors).transform("sum")
    market_rank = values.rank(pct=True, method="average") * 100
    return sector_rank.where(sector_count >= min_sector_size, market_rank)


def _mean_with_minimum(
    frame: pd.DataFrame,
    columns: list[str],
    minimum: int,
) -> tuple[pd.Series, pd.Series]:
    valid_count = frame[columns].notna().sum(axis=1)
    score = frame[columns].mean(axis=1, skipna=True)
    return score.where(valid_count >= minimum), valid_count


@dataclass
class FundamentalsSnapshot:
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
    ebitda_yield: float
    book_yield: float
    sales_yield: float

    # Profitability (ART)
    roe: float
    roa: float
    roic: float
    grossmargin: float
    ebitdamargin: float
    netmargin: float
    fcf: float
    opinc: float
    gross_profitability: float
    cfo_to_assets: float
    accrual_quality: float

    # Earnings quality (ART)
    ncfo: float
    capex: float
    ebit: float
    intexp: float
    interest_coverage: float  # ebit / intexp
    capex_to_ocf: float  # abs(capex) / ncfo

    # Efficiency (ART)
    assetturnover: float
    rnd: float  # absolute R&D spend
    rnd_intensity: float  # rnd / revenue

    # Balance sheet (ART)
    de: float
    currentratio: float
    cashneq: float
    workingcapital: float
    payoutratio: float
    net_payout_yield: float

    # Reference levels (ART)
    revenue: float
    eps: float

    # Growth (YoY from ARQ: most recent quarter vs same quarter 1 year prior)
    revenue_growth_yoy: float
    eps_growth_yoy: float
    grossmargin_change_yoy: float
    opinc_growth_yoy: float

    # Multi-year quality evidence from annual ART observations
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

    # Cross-sectional percentiles
    roe_percentile: float
    revenue_growth_percentile: float
    earnings_yield_percentile: float
    fcf_yield_percentile: float
    ebitda_yield_percentile: float
    book_yield_percentile: float
    sales_yield_percentile: float
    value_composite_score: float
    value_composite_percentile: float
    valid_value_metrics: int
    de_percentile: float
    currentratio_percentile: float
    quality_profitability_score: float
    quality_growth_score: float
    quality_safety_score: float
    quality_capital_discipline_score: float
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

    def value_metrics(self) -> dict[str, float]:
        return {
            "earnings_yield": self.earnings_yield,
            "fcf_yield": self.fcf_yield,
            "ebitda_yield": self.ebitda_yield,
            "book_yield": self.book_yield,
            "sales_yield": self.sales_yield,
        }

    def value_percentiles(self) -> dict[str, float]:
        return {
            "earnings_yield": self.earnings_yield_percentile,
            "fcf_yield": self.fcf_yield_percentile,
            "ebitda_yield": self.ebitda_yield_percentile,
            "book_yield": self.book_yield_percentile,
            "sales_yield": self.sales_yield_percentile,
            "composite": self.value_composite_percentile,
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

    def earnings_quality(self) -> dict[str, bool]:
        no_interest = pd.isna(self.interest_coverage)
        return {
            "interest_covered": no_interest or self.interest_coverage > 3.0,
            "strong_coverage": no_interest or self.interest_coverage > 10.0,
            "low_capex_intensity": self.capex_to_ocf < 0.5,
            "ocf_positive": self.ncfo > 0,
        }

    def efficiency(self) -> dict[str, bool]:
        return {
            "asset_turnover_ok": self.assetturnover > 0.5,
            "investing_in_rnd": self.rnd_intensity > 0.05,
            "high_rnd": self.rnd_intensity > 0.15,
        }

    def balance_sheet_health(self) -> dict[str, bool]:
        return {
            "low_leverage": self.de < 1.0,
            "current_ratio_ok": self.currentratio > 1.5,
            "has_cash": self.cashneq > 0,
            "positive_working_cap": self.workingcapital > 0,
            "sustainable_payout": 0 <= self.payoutratio < 0.75,
        }

    def growth_momentum(self) -> dict[str, bool]:
        return {
            "revenue_growing": self.revenue_growth_yoy > 0,
            "revenue_strong": self.revenue_growth_yoy > 0.10,
            "eps_growing": self.eps_growth_yoy > 0,
            "eps_strong": self.eps_growth_yoy > 0.10,
            "margin_expanding": self.grossmargin_change_yoy > 0,
            "opinc_growing": self.opinc_growth_yoy > 0,
        }

    def quality_pillars(self) -> dict[str, float]:
        return {
            "profitability": self.quality_profitability_score,
            "growth": self.quality_growth_score,
            "safety": self.quality_safety_score,
            "capital_discipline": self.quality_capital_discipline_score,
            "composite": self.quality_composite_score,
            "sector_percentile": self.quality_composite_percentile,
        }

    def quality_screen(self) -> dict[str, bool]:
        hard_distress = (
            self.ncfo < 0
            or (self.fcf < 0 and self.netmargin < 0)
            or 0 < self.interest_coverage < 1.5
            or self.de_percentile >= 95
        )
        return {
            "complete_multi_year_history": bool(self.complete_multi_year_history),
            "quality_top_30pct": self.quality_composite_percentile >= 70,
            "profitability_strong": self.quality_profitability_score >= 60,
            "safety_not_weak": self.quality_safety_score >= 30,
            "operating_cash_flow_positive": self.ncfo > 0,
            "no_hard_distress": not hard_distress,
        }

    def quality_score(self) -> float:
        if pd.isna(self.quality_composite_score):
            return float("nan")
        return self.quality_composite_score / 100

    def financial_health(self) -> dict[str, bool | None]:
        def check(value: float, predicate) -> bool | None:
            if pd.isna(value):
                return None
            return bool(predicate(value))

        direction_known = pd.notna(self.grossmargin_change_yoy) or pd.notna(
            self.opinc_growth_yoy
        )
        operating_direction_ok = None
        if direction_known:
            operating_direction_ok = bool(
                (
                    pd.notna(self.grossmargin_change_yoy)
                    and self.grossmargin_change_yoy >= 0
                )
                or (pd.notna(self.opinc_growth_yoy) and self.opinc_growth_yoy >= 0)
            )

        if pd.isna(self.intexp):
            interest_covered = None
        elif self.intexp <= 0:
            interest_covered = True
        else:
            interest_covered = check(self.interest_coverage, lambda value: value >= 1.5)

        return {
            "roa_positive": check(self.roa, lambda value: value > 0),
            "roic_positive": check(self.roic, lambda value: value > 0),
            "gross_profitability_positive": check(
                self.gross_profitability, lambda value: value > 0
            ),
            "operating_cash_flow_positive": check(self.ncfo, lambda value: value > 0),
            "free_cash_flow_positive": check(self.fcf, lambda value: value > 0),
            "interest_covered": interest_covered,
            "leverage_not_extreme": check(self.de_percentile, lambda value: value < 90),
            "liquidity_not_extreme": check(
                self.currentratio_percentile, lambda value: value >= 10
            ),
            "revenue_not_collapsing": check(
                self.revenue_growth_yoy, lambda value: value > -0.20
            ),
            "operating_direction_ok": operating_direction_ok,
        }

    def financial_health_score(self) -> float:
        known = [
            value for value in self.financial_health().values() if value is not None
        ]
        if not known:
            return float("nan")
        return sum(known) / len(known)

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

    def _compute_growth(self, arq: pd.DataFrame) -> pd.DataFrame:
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
                    "revenue_growth_yoy": _safe_growth(
                        latest["revenue"], prior["revenue"]
                    ),
                    "eps_growth_yoy": _safe_growth(latest["eps"], prior["eps"]),
                    "grossmargin_change_yoy": (
                        latest["grossmargin"] - prior["grossmargin"]
                        if pd.notna(latest["grossmargin"])
                        and pd.notna(prior["grossmargin"])
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

    def _compute_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        def safe_div(a, b, fallback=float("nan")):
            mask = pd.notna(a) & pd.notna(b) & (b != 0)
            result = pd.Series(fallback, index=a.index, dtype=float)
            result[mask] = a[mask] / b[mask]
            return result

        df["interest_coverage"] = safe_div(df["ebit"], df["intexp"])
        # Only meaningful when OCF is positive; negative OCF makes ratio negative/misleading
        df["capex_to_ocf"] = safe_div(
            df["capex"].abs(), df["ncfo"].where(df["ncfo"] > 0)
        )
        df["rnd_intensity"] = safe_div(df["rnd"], df["revenue"])
        df["gross_profitability"] = safe_div(df["gp"], df["assets"])
        df["cfo_to_assets"] = safe_div(df["ncfo"], df["assets"])
        df["accrual_quality"] = safe_div(df["ncfo"] - df["netinc"], df["assets"])
        payout = df[["ncfcommon", "ncfdiv"]].sum(axis=1, min_count=1)
        df["net_payout_yield"] = safe_div(
            -payout,
            df["marketcap"].where(df["marketcap"] > 0),
        )
        df["earnings_yield"] = _positive_inverse(df["pe"])
        df["fcf_yield"] = _positive_ratio(df["fcf"], df["marketcap"])
        df["ebitda_yield"] = _positive_inverse(df["evebitda"])
        df["book_yield"] = _positive_inverse(df["pb"])
        df["sales_yield"] = _positive_inverse(df["ps"])
        return df

    def _compute_quality_history(self, art: pd.DataFrame) -> pd.DataFrame:
        if art.empty:
            return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))

        art = self._compute_derived(art.copy())
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
                if (
                    distance.loc[closest_index].days
                    <= MAX_HISTORY_OBSERVATION_DISTANCE_DAYS
                ):
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

            def change(column: str) -> float:
                if prior is None or not complete_history:
                    return float("nan")
                now = latest[column]
                then = prior[column]
                if pd.isna(now) or pd.isna(then):
                    return float("nan")
                return now - then

            def volatility(column: str) -> float:
                if not complete_history:
                    return float("nan")
                values = pd.to_numeric(window[column], errors="coerce").dropna()
                if len(values) < 3:
                    return float("nan")
                return values.std(ddof=0)

            rows.append(
                {
                    "ticker": ticker,
                    "gross_profitability_change_5y": change("gross_profitability"),
                    "roa_change_5y": change("roa"),
                    "roic_change_5y": change("roic"),
                    "cfo_to_assets_change_5y": change("cfo_to_assets"),
                    "grossmargin_change_5y": change("grossmargin"),
                    "share_dilution_5y": (
                        _safe_growth(latest["shareswa"], prior["shareswa"])
                        if prior is not None and complete_history
                        else float("nan")
                    ),
                    "de_change_5y": change("de"),
                    "roe_volatility_5y": volatility("roe"),
                    "grossmargin_volatility_5y": volatility("grossmargin"),
                    "quality_history_years": history_years,
                    "quality_history_observations": observations,
                    "complete_multi_year_history": complete_history,
                }
            )

        if not rows:
            return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))
        return pd.DataFrame(rows).set_index("ticker")

    def _attach_sectors(self, df: pd.DataFrame) -> pd.DataFrame:
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

    def _compute_cross_section(self, universe: pd.DataFrame) -> pd.DataFrame:
        universe = self._attach_sectors(universe)

        universe["roe_percentile"] = (
            universe["roe"].rank(pct=True, method="average") * 100
        )
        universe["de_percentile"] = _rank_within_sector(
            universe["de"], universe["sector"]
        )
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
        universe.loc[universe["valid_value_metrics"] < 2, "value_composite_score"] = (
            np.nan
        )
        universe["value_composite_percentile"] = _rank_within_sector(
            universe["value_composite_score"], universe["sector"]
        )

        pillar_columns = []
        for pillar, metrics in QUALITY_PILLAR_METRICS.items():
            metric_percentiles = []
            for metric, direction in metrics.items():
                percentile_column = f"_quality_{metric}_percentile"
                values = universe.get(
                    metric,
                    pd.Series(np.nan, index=universe.index, dtype=float),
                )
                universe[percentile_column] = _rank_within_sector(
                    values * direction,
                    universe["sector"],
                )
                metric_percentiles.append(percentile_column)

            score_column = f"quality_{pillar}_score"
            count_column = f"_valid_quality_{pillar}_metrics"
            universe[score_column], universe[count_column] = _mean_with_minimum(
                universe,
                metric_percentiles,
                QUALITY_PILLAR_MINIMUMS[pillar],
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
            universe[required_pillars].isna().any(axis=1),
            "quality_composite_score",
        ] = np.nan
        universe["quality_composite_percentile"] = _rank_within_sector(
            universe["quality_composite_score"],
            universe["sector"],
        )
        return universe

    def load_data(self) -> None:
        art = fundamentals_repo.get_latest(self.tickers, "ART", self.signal_day)
        art = art.set_index("ticker")
        art = self._compute_derived(art)

        # Cross-sectional ranks use the full ART universe (point-in-time). TICKERS
        # currently stores only current sector classifications; historical sector
        # versioning remains a separate data-model requirement.
        universe = fundamentals_repo.get_latest(None, "ART", self.signal_day)
        universe = universe.set_index("ticker")
        universe = self._compute_derived(universe)
        quality_history = self._compute_quality_history(self._load_art_history())
        universe = universe.join(quality_history, how="left")
        universe = self._compute_cross_section(universe)

        # YoY growth (and its percentile) are computed across the full universe so
        # the percentile is independent of the request batch; the batch's own
        # growth values are a subset of this same computation.
        growth = self._compute_growth(self._load_arq(universe.index.tolist()))
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
            ebitda_yield=g("ebitda_yield"),
            book_yield=g("book_yield"),
            sales_yield=g("sales_yield"),
            roe=g("roe"),
            roa=g("roa"),
            roic=g("roic"),
            grossmargin=g("grossmargin"),
            ebitdamargin=g("ebitdamargin"),
            netmargin=g("netmargin"),
            fcf=g("fcf"),
            opinc=g("opinc"),
            gross_profitability=g("gross_profitability"),
            cfo_to_assets=g("cfo_to_assets"),
            accrual_quality=g("accrual_quality"),
            ncfo=g("ncfo"),
            capex=g("capex"),
            ebit=g("ebit"),
            intexp=g("intexp"),
            interest_coverage=g("interest_coverage"),
            capex_to_ocf=g("capex_to_ocf"),
            assetturnover=g("assetturnover"),
            rnd=g("rnd"),
            rnd_intensity=g("rnd_intensity"),
            de=g("de"),
            currentratio=g("currentratio"),
            cashneq=g("cashneq"),
            workingcapital=g("workingcapital"),
            payoutratio=g("payoutratio"),
            net_payout_yield=g("net_payout_yield"),
            revenue=g("revenue"),
            eps=g("eps"),
            revenue_growth_yoy=g("revenue_growth_yoy"),
            eps_growth_yoy=g("eps_growth_yoy"),
            grossmargin_change_yoy=g("grossmargin_change_yoy"),
            opinc_growth_yoy=g("opinc_growth_yoy"),
            gross_profitability_change_5y=g("gross_profitability_change_5y"),
            roa_change_5y=g("roa_change_5y"),
            roic_change_5y=g("roic_change_5y"),
            cfo_to_assets_change_5y=g("cfo_to_assets_change_5y"),
            grossmargin_change_5y=g("grossmargin_change_5y"),
            share_dilution_5y=g("share_dilution_5y"),
            de_change_5y=g("de_change_5y"),
            roe_volatility_5y=g("roe_volatility_5y"),
            grossmargin_volatility_5y=g("grossmargin_volatility_5y"),
            quality_history_years=g("quality_history_years"),
            quality_history_observations=g("quality_history_observations"),
            complete_multi_year_history=g("complete_multi_year_history"),
            roe_percentile=g("roe_percentile"),
            revenue_growth_percentile=g("revenue_growth_percentile"),
            earnings_yield_percentile=g("earnings_yield_percentile"),
            fcf_yield_percentile=g("fcf_yield_percentile"),
            ebitda_yield_percentile=g("ebitda_yield_percentile"),
            book_yield_percentile=g("book_yield_percentile"),
            sales_yield_percentile=g("sales_yield_percentile"),
            value_composite_score=g("value_composite_score"),
            value_composite_percentile=g("value_composite_percentile"),
            valid_value_metrics=g("valid_value_metrics"),
            de_percentile=g("de_percentile"),
            currentratio_percentile=g("currentratio_percentile"),
            quality_profitability_score=g("quality_profitability_score"),
            quality_growth_score=g("quality_growth_score"),
            quality_safety_score=g("quality_safety_score"),
            quality_capital_discipline_score=g("quality_capital_discipline_score"),
            quality_composite_score=g("quality_composite_score"),
            quality_composite_percentile=g("quality_composite_percentile"),
            valid_quality_pillars=g("valid_quality_pillars"),
        )


def print_snapshot_report(snap: FundamentalsSnapshot) -> None:
    sections = {
        "Valuation": snap.valuation(),
        "Value Metrics": snap.value_metrics(),
        "Value Percentiles": snap.value_percentiles(),
        "Profitability": snap.profitability(),
        "Earnings Quality": snap.earnings_quality(),
        "Financial Health": snap.financial_health(),
        "Quality Pillars": snap.quality_pillars(),
        "Quality Screen": snap.quality_screen(),
        "Efficiency": snap.efficiency(),
        "Balance Sheet": snap.balance_sheet_health(),
        "Growth": snap.growth_momentum(),
        "Risk Flags": snap.risk_flags(),
    }
    print(
        f"\n=== {snap.ticker} | {snap.signal_day.date()} (period {snap.calendardate.date()}, filed {snap.datekey.date()}) ==="
    )
    # print(snap)
    print(f"Quality Score: {snap.quality_score():.3f}")
    print(f"Financial Health Score: {snap.financial_health_score():.3f}")
    for title, values in sections.items():
        print(f"{title}: {values}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2024-06-30")
    tickers = ["AAPL", "MSFT", "GOOGL"]

    model = FundamentalsModel(signal_day=signal_day, tickers=tickers)
    for tkr in tickers:
        print_snapshot_report(model.build_snapshot(tkr))
