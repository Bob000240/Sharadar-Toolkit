"""Point-in-time fundamental rows with optional fact attachments."""

import numpy as np
import pandas as pd

import database.source.fundamentals_repo as fundamentals_repo
from data.signals.sig import Signals


GROWTH_COLUMNS = (
    "revenue_growth_yoy",
    "eps_growth_yoy",
    "grossmargin_change_yoy",
    "opinc_growth_yoy",
)

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
    "quality_history_observations",
    "complete_multi_year_history",
)

QUALITY_HISTORY_TARGET_YEARS = 5
MIN_QUALITY_HISTORY_OBSERVATIONS = 6


class FundamentalSignals(Signals):
    """SQL-backed fundamental facts with opt-in DataFrame attachments."""

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Return latest point-in-time ART rows directly from the SQL repository."""
        signal_day = pd.Timestamp(signal_day)
        frame = fundamentals_repo.get_latest_rows(tickers, "ART", signal_day)
        if frame.empty:
            return pd.DataFrame().rename_axis("ticker")

        frame = frame.set_index("ticker")
        if tickers is not None:
            ordered = [ticker for ticker in tickers if ticker in frame.index]
            frame = frame.loc[ordered]
        return frame.copy()

    @classmethod
    def attach_growth(
        cls,
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Attach latest year-over-year facts from quarterly fundamentals."""
        frame = frame.copy()
        signal_day = pd.Timestamp(signal_day)
        growth_start = signal_day - pd.Timedelta(days=730)
        arq = fundamentals_repo.get(
            tickers=frame.index.astype(str).tolist(),
            dimension="ARQ",
            start_date=str(growth_start.date()),
            end_date=str(signal_day.date()),
        )
        if not arq.empty:
            arq = arq[pd.to_datetime(arq["datekey"]) <= signal_day]
        return frame.join(cls._calculate_growth(arq), how="left")

    @classmethod
    def attach_history_features(
        cls,
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Attach five-year change, volatility, and history-sufficiency facts."""
        frame = frame.copy()
        signal_day = pd.Timestamp(signal_day)
        history_start = signal_day - pd.DateOffset(years=6)
        annual_history = fundamentals_repo.get(
            tickers=frame.index.astype(str).tolist(),
            dimension="ARY",
            start_date=str(history_start.date()),
            end_date=str(signal_day.date()),
        )
        if not annual_history.empty:
            annual_history = annual_history[
                pd.to_datetime(annual_history["datekey"]) <= signal_day
            ]
        history = cls._calculate_history_features(annual_history)
        return frame.join(history, how="left")

    @classmethod
    def attach_ratios(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach ratios that combine multiple stored fundamental columns."""
        frame = frame.copy()
        frame["fcf_yield"] = cls.positive_ratio(frame["fcf"], frame["marketcap"])
        frame["interest_coverage"] = cls.safe_div(frame["ebit"], frame["intexp"])
        frame["gross_profitability"] = cls.safe_div(frame["gp"], frame["assets"])
        frame["cfo_to_assets"] = cls.safe_div(frame["ncfo"], frame["assets"])
        frame["accruals"] = cls.safe_div(
            frame["netinc"] - frame["ncfo"],
            frame["assets"],
        )
        payout = frame[["ncfcommon", "ncfdiv"]].sum(axis=1, min_count=1)
        frame["net_payout_yield"] = cls.safe_div(
            -payout,
            frame["marketcap"].where(frame["marketcap"] > 0),
        )
        return frame

    @classmethod
    def _calculate_growth(cls, arq: pd.DataFrame) -> pd.DataFrame:
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
                    "revenue_growth_yoy": cls.safe_growth(
                        latest["revenue"],
                        prior["revenue"],
                    ),
                    "eps_growth_yoy": cls.safe_growth(
                        latest["eps"],
                        prior["eps"],
                    ),
                    "grossmargin_change_yoy": (
                        latest["grossmargin"] - prior["grossmargin"]
                        if pd.notna(latest["grossmargin"])
                        and pd.notna(prior["grossmargin"])
                        else np.nan
                    ),
                    "opinc_growth_yoy": cls.safe_growth(
                        latest["opinc"],
                        prior["opinc"],
                    ),
                }
            )

        if not rows:
            return pd.DataFrame(columns=list(GROWTH_COLUMNS))
        return pd.DataFrame(rows).set_index("ticker")

    @classmethod
    def _calculate_history_features(cls, ary: pd.DataFrame) -> pd.DataFrame:
        if ary.empty:
            return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))

        ary = ary.copy()
        ary["gross_profitability"] = cls.safe_div(ary["gp"], ary["assets"])
        ary["cfo_to_assets"] = cls.safe_div(ary["ncfo"], ary["assets"])
        ary["calendardate"] = pd.to_datetime(ary["calendardate"])
        ary["datekey"] = pd.to_datetime(ary["datekey"])
        rows = []

        for ticker, group in ary.groupby("ticker"):
            group = group.dropna(subset=["calendardate"])
            group = group.sort_values(["calendardate", "datekey"])
            group = group.drop_duplicates("calendardate", keep="last")
            if group.empty:
                continue

            latest = group.iloc[-1]
            cutoff = latest["calendardate"] - pd.DateOffset(
                years=QUALITY_HISTORY_TARGET_YEARS
            )
            window = group[group["calendardate"] >= cutoff]
            prior = window.iloc[0] if not window.empty else None
            observations = len(window)
            complete_history = observations >= MIN_QUALITY_HISTORY_OBSERVATIONS
            rows.append(
                {
                    "ticker": ticker,
                    "gross_profitability_change_5y": cls._history_change(
                        latest,
                        prior,
                        complete_history,
                        "gross_profitability",
                    ),
                    "roa_change_5y": cls._history_change(
                        latest,
                        prior,
                        complete_history,
                        "roa",
                    ),
                    "roic_change_5y": cls._history_change(
                        latest,
                        prior,
                        complete_history,
                        "roic",
                    ),
                    "cfo_to_assets_change_5y": cls._history_change(
                        latest,
                        prior,
                        complete_history,
                        "cfo_to_assets",
                    ),
                    "grossmargin_change_5y": cls._history_change(
                        latest,
                        prior,
                        complete_history,
                        "grossmargin",
                    ),
                    "share_dilution_5y": (
                        cls.safe_growth(latest["shareswa"], prior["shareswa"])
                        if prior is not None and complete_history
                        else np.nan
                    ),
                    "de_change_5y": cls._history_change(
                        latest,
                        prior,
                        complete_history,
                        "de",
                    ),
                    "roe_volatility_5y": cls._history_volatility(
                        window,
                        complete_history,
                        "roe",
                    ),
                    "grossmargin_volatility_5y": cls._history_volatility(
                        window,
                        complete_history,
                        "grossmargin",
                    ),
                    "quality_history_observations": observations,
                    "complete_multi_year_history": complete_history,
                }
            )

        return pd.DataFrame(rows).set_index("ticker")

    @staticmethod
    def _history_change(latest, prior, complete_history, column) -> float:
        if prior is None or not complete_history:
            return float("nan")
        now, then = latest[column], prior[column]
        if pd.isna(now) or pd.isna(then):
            return float("nan")
        return now - then

    @staticmethod
    def _history_volatility(
        window: pd.DataFrame,
        complete_history: bool,
        column: str,
    ) -> float:
        if not complete_history:
            return np.nan
        values = pd.to_numeric(window[column], errors="coerce").dropna()
        if len(values) < 3:
            return np.nan
        return values.std(ddof=0)


if __name__ == "__main__":
    as_of = pd.Timestamp("2024-06-30")
    signals = FundamentalSignals.get_signals(
        ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA"],
        as_of,
    )
    signals = FundamentalSignals.attach_sectors(signals)
    signals = FundamentalSignals.attach_history_features(signals, as_of)
    signals = FundamentalSignals.attach_ratios(signals)
    signals = FundamentalSignals.attach_growth(signals, as_of)
    signals = FundamentalSignals.attach_sector_ranks(
        signals,
        {"pe": -1, "roic": 1, "fcf_yield": 1},
        positive_only=("pe",),
    )
    print(signals)
