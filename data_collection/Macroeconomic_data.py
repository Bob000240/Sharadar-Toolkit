import yfinance as yf
import pandas as pd
from fredapi import Fred
import os
from dotenv import load_dotenv

load_dotenv()


def _fred_series(fred: Fred, series_id: str, start: str, end: str) -> pd.Series:
    """Fetch a FRED series and forward-fill to daily frequency."""
    s = fred.get_series(series_id, observation_start=start, observation_end=end)
    return s.reindex(pd.date_range(start, end, freq="D")).ffill()


def _yf_series(ticker: str, start: str, end: str, field: str = "Close") -> pd.Series:
    """Fetch a daily price series from yfinance."""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        return pd.Series(dtype=float)
    return df[field].squeeze()


class MacroeconomicData:
    """
    Collects daily macro indicators from FRED and yfinance.

    FRED series used:
        DGS10        — 10-year Treasury yield (%)
        DGS2         — 2-year Treasury yield (%)
        DFII10       — 10-year TIPS yield / real yield (%)
        CPIAUCSL     — CPI all items (index level; YoY computed here)
        UNRATE       — Unemployment rate (%)
        BAMLH0A0HYM2 — ICE BofA HY option-adjusted spread (%)
        BAMLC0A0CM   — ICE BofA IG option-adjusted spread (%)

    yfinance tickers used:
        ^VIX         — CBOE Volatility Index
    """

    def __init__(self):
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            raise ValueError("FRED_API_KEY not set in environment.")
        self.fred = Fred(api_key=api_key)

    def get_macro(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Returns a DataFrame with one row per trading day, columns matching
        the macro_repository schema.

        start_date / end_date: "YYYY-MM-DD" strings.
        """
        print("Fetching FRED series...")
        yield_10y = _fred_series(self.fred, "DGS10",        start_date, end_date)
        yield_2y  = _fred_series(self.fred, "DGS2",         start_date, end_date)
        real_yield = _fred_series(self.fred, "DFII10",       start_date, end_date)
        cpi        = _fred_series(self.fred, "CPIAUCSL",     start_date, end_date)
        unrate     = _fred_series(self.fred, "UNRATE",       start_date, end_date)
        hy_spread  = _fred_series(self.fred, "BAMLH0A0HYM2", start_date, end_date)
        ig_spread  = _fred_series(self.fred, "BAMLC0A0CM",   start_date, end_date)

        print("Fetching VIX from yfinance...")
        vix = _yf_series("^VIX", start_date, end_date)

        # Align all series on a common daily index
        idx = pd.date_range(start_date, end_date, freq="D")
        df = pd.DataFrame(index=idx)
        df["yield_10y"]        = yield_10y.reindex(idx).ffill()
        df["yield_2y"]         = yield_2y.reindex(idx).ffill()
        df["real_yield"]       = real_yield.reindex(idx).ffill()
        df["cpi_raw"]          = cpi.reindex(idx).ffill()
        df["unemployment_rate"] = unrate.reindex(idx).ffill()
        df["credit_spread_hy"] = hy_spread.reindex(idx).ffill()
        df["credit_spread_ig"] = ig_spread.reindex(idx).ffill()
        df["vix"]              = vix.reindex(idx).ffill()

        # Derived fields
        df["yield_curve"] = df["yield_10y"] - df["yield_2y"]
        df["cpi_yoy"]     = df["cpi_raw"].pct_change(365) * 100   # daily index → YoY %

        df = df.drop(columns=["cpi_raw"])
        df.index.name = "date"
        df = df.reset_index()

        # Keep only days where at least yields and VIX are present
        df = df.dropna(subset=["yield_10y", "yield_2y", "vix"])

        # Reorder to match repo schema
        df = df[[
            "date",
            "yield_10y", "yield_2y", "yield_curve", "real_yield",
            "cpi_yoy", "unemployment_rate",
            "credit_spread_hy", "credit_spread_ig",
            "vix",
        ]]

        return df


if __name__ == "__main__":
    import database.macro_repository as macro_repo

    start = "2024-01-01"
    end   = pd.Timestamp.today().strftime("%Y-%m-%d")

    macro_repo.create_macro_table()

    md = MacroeconomicData()
    df = md.get_macro(start, end)

    print(df.tail(10).to_string())
    print(f"\n{len(df)} rows fetched.")

    macro_repo.insert_macro(df)
    print("Inserted successfully.")
