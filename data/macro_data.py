import os
import pandas as pd
from fredapi import Fred
from dotenv import load_dotenv

load_dotenv()

# FRED series ID -> column name
SERIES = {
    # --- Yields ---
    "DGS1MO": "yield_1m",
    "DGS3MO": "yield_3m",
    "DGS6MO": "yield_6m",
    "DGS1": "yield_1y",
    "DGS2": "yield_2y",
    "DGS5": "yield_5y",
    "DGS10": "yield_10y",
    "DGS20": "yield_20y",
    "DGS30": "yield_30y",
    # --- Real yields (TIPS) ---
    "DFII5": "real_yield_5y",
    "DFII10": "real_yield_10y",
    "DFII20": "real_yield_20y",
    # --- Breakeven inflation ---
    "T5YIE": "breakeven_5y",
    "T10YIE": "breakeven_10y",
    # --- Policy rates ---
    "FEDFUNDS": "fed_funds_rate",
    "SOFR": "sofr",
    # --- Credit spreads ---
    "BAMLH0A0HYM2": "spread_hy",
    "BAMLC0A0CM": "spread_ig",
    "BAMLH0A0HYM2EY": "yield_hy",
    "BAMLC0A0CMEY": "yield_ig",
    # --- Inflation ---
    "CPIAUCSL": "cpi",
    "CPILFESL": "cpi_core",
    "PCEPI": "pce",
    "PCEPILFE": "pce_core",
    # --- Labor ---
    "UNRATE": "unemployment_rate",
    "ICSA": "jobless_claims",
    "PAYEMS": "nonfarm_payrolls",
    # --- Activity ---
    "INDPRO": "industrial_production",
    "RETAILSMNSA": "retail_sales",
    "GDP": "gdp",
    # --- Money supply ---
    "M2SL": "m2",
    # --- Housing ---
    "HOUST": "housing_starts",
    "CSUSHPISA": "case_shiller_hpi",
    # --- Commodities ---
    "DCOILWTICO": "oil_wti",
    # --- Dollar ---
    "DTWEXBGS": "dxy",
    "DEXUSEU": "eurusd",
    "DEXJPUS": "usdjpy",
    # --- Volatility ---
    "VIXCLS": "vix",
}

RELEASE_SENSITIVE_SERIES = {
    "FEDFUNDS",
    "CPIAUCSL",
    "CPILFESL",
    "PCEPI",
    "PCEPILFE",
    "UNRATE",
    "ICSA",
    "PAYEMS",
    "INDPRO",
    "RETAILSMNSA",
    "GDP",
    "M2SL",
    "HOUST",
    "CSUSHPISA",
}

AVAILABILITY_COLUMNS = {
    "rates_as_of": ("yield_2y", "yield_10y", "real_yield_10y"),
    "credit_as_of": ("spread_hy", "spread_ig"),
    "inflation_as_of": ("cpi", "cpi_core"),
    "unemployment_as_of": ("unemployment_rate",),
    "claims_as_of": ("jobless_claims",),
    "volatility_as_of": ("vix",),
}


def _first_release_events(releases: pd.DataFrame) -> pd.DataFrame:
    """Return one point-in-time-safe event per FRED observation."""
    if releases.empty:
        return pd.DataFrame(columns=["observation_date", "available_date", "value"])

    events = releases.rename(
        columns={"date": "observation_date", "realtime_start": "available_date"}
    )[["observation_date", "available_date", "value"]].copy()
    events["observation_date"] = pd.to_datetime(events["observation_date"])
    events["available_date"] = pd.to_datetime(events["available_date"])
    events["value"] = pd.to_numeric(events["value"], errors="coerce")
    events = events.dropna(subset=["observation_date", "available_date", "value"])
    return (
        events.sort_values(["observation_date", "available_date"])
        .drop_duplicates("observation_date", keep="first")
        .reset_index(drop=True)
    )


def _events_to_daily(
    events: pd.DataFrame, index: pd.DatetimeIndex
) -> tuple[pd.Series, pd.Series]:
    """Publish event values no earlier than their availability date."""
    if events.empty:
        empty_values = pd.Series(index=index, dtype=float)
        empty_dates = pd.Series(index=index, dtype="datetime64[ns]")
        return empty_values, empty_dates

    published = (
        events.sort_values(["available_date", "observation_date"])
        .drop_duplicates("available_date", keep="last")
        .set_index("available_date")
    )
    expanded_index = index.union(published.index).sort_values()
    values = published["value"].reindex(expanded_index).ffill().reindex(index)
    available_dates = pd.Series(published.index, index=published.index)
    available_dates = (
        available_dates.reindex(expanded_index).ffill().reindex(index)
    )
    return values, available_dates


def _yoy_events(events: pd.DataFrame, periods: int = 12) -> pd.DataFrame:
    """Calculate YoY changes at observation frequency before daily alignment."""
    result = events.sort_values("observation_date").copy()
    result["value"] = result["value"].pct_change(periods=periods, fill_method=None) * 100
    return result.dropna(subset=["value"])


class MacroData:
    def __init__(self, fred: Fred | None = None):
        if fred is not None:
            self._fred = fred
            return

        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            raise ValueError("FRED_API_KEY not set")
        self._fred = Fred(api_key=api_key)

    def _fetch_events(self, series_id: str, start: str, end: str) -> pd.DataFrame:
        fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=500)).strftime("%Y-%m-%d")
        if series_id in RELEASE_SENSITIVE_SERIES:
            releases = self._fred.get_series_all_releases(
                series_id,
                realtime_start=fetch_start,
                realtime_end=end,
            )
            events = _first_release_events(releases)
            return events.loc[
                events["observation_date"] >= pd.Timestamp(fetch_start)
            ].reset_index(drop=True)

        series = self._fred.get_series(
            series_id,
            observation_start=fetch_start,
            observation_end=end,
        ).dropna()
        return pd.DataFrame(
            {
                "observation_date": pd.to_datetime(series.index),
                "available_date": pd.to_datetime(series.index),
                "value": pd.to_numeric(series.to_numpy(), errors="coerce"),
            }
        )

    def get_macro(self, start_date: str, end_date: str) -> pd.DataFrame:
        idx = pd.date_range(start_date, end_date, freq="D")
        df = pd.DataFrame(index=idx)
        available: dict[str, pd.Series] = {}
        events_by_column: dict[str, pd.DataFrame] = {}

        for series_id, col in SERIES.items():
            events = self._fetch_events(series_id, start_date, end_date)
            events_by_column[col] = events
            df[col], available[col] = _events_to_daily(events, idx)

        # Derived fields
        df["yield_curve_2_10"] = df["yield_10y"] - df["yield_2y"]
        df["yield_curve_3m_10"] = df["yield_10y"] - df["yield_3m"]
        for source_col, output_col in (
            ("cpi", "cpi_yoy"),
            ("cpi_core", "cpi_core_yoy"),
            ("pce", "pce_yoy"),
        ):
            df[output_col], _ = _events_to_daily(
                _yoy_events(events_by_column[source_col]), idx
            )

        for output_col, source_cols in AVAILABILITY_COLUMNS.items():
            source_dates = pd.concat(
                [available[col] for col in source_cols], axis=1
            )
            df[output_col] = source_dates.min(axis=1)

        df.index.name = "date"
        df = df.reset_index()
        df = df.dropna(subset=["yield_10y", "vix"])
        return df


if __name__ == "__main__":
    md = MacroData()
    df = md.get_macro("2024-01-01", pd.Timestamp.today().strftime("%Y-%m-%d"))
    print(df.tail(5))
    print(f"\n{len(df)} rows, {len(df.columns)} columns")
