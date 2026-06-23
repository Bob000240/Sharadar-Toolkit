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
    "TEDRATE": "ted_spread",
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


class MacroData:
    def __init__(self):
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            raise ValueError("FRED_API_KEY not set")
        self._fred = Fred(api_key=api_key)

    def _fetch(self, series_id: str, start: str, end: str) -> pd.Series:
        try:
            s = self._fred.get_series(
                series_id, observation_start=start, observation_end=end
            )
            return s.reindex(pd.date_range(start, end, freq="D")).ffill()
        except Exception as e:
            print(f"Warning: could not fetch {series_id}: {e}")
            return pd.Series(dtype=float, index=pd.date_range(start, end, freq="D"))

    def get_macro(self, start_date: str, end_date: str) -> pd.DataFrame:
        idx = pd.date_range(start_date, end_date, freq="D")
        df = pd.DataFrame(index=idx)

        for series_id, col in SERIES.items():
            df[col] = self._fetch(series_id, start_date, end_date).reindex(idx).ffill()

        # Derived fields
        df["yield_curve_2_10"] = df["yield_10y"] - df["yield_2y"]
        df["yield_curve_3m_10"] = df["yield_10y"] - df["yield_3m"]
        df["cpi_yoy"] = df["cpi"].pct_change(365) * 100
        df["cpi_core_yoy"] = df["cpi_core"].pct_change(365) * 100
        df["pce_yoy"] = df["pce"].pct_change(365) * 100

        df.index.name = "date"
        df = df.reset_index()
        df = df.dropna(subset=["yield_10y", "vix"])
        return df


if __name__ == "__main__":
    md = MacroData()
    df = md.get_macro("2024-01-01", pd.Timestamp.today().strftime("%Y-%m-%d"))
    print(df.tail(5))
    print(f"\n{len(df)} rows, {len(df.columns)} columns")
