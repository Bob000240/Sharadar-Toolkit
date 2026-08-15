"""Point-in-time fundamental facts with optional attachments.

Sharadar dates every filing twice: ``calendardate`` is the period reported on,
``datekey`` the day it reached the tape, and the two sit months apart. Every
read here is bounded on ``datekey``, so a report is invisible until the day it
was actually published.

Three dimensions are used. ART carries the latest trailing-twelve-month figures,
ARQ the quarterly series behind year-over-year growth, and ARY the annual series
behind the five-year change and volatility features.
"""

import numpy as np
import pandas as pd

import database.source.fundamentals_repo as fundamentals_repo
from research.signals.sig import Signals


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
MIN_VOLATILITY_OBSERVATIONS = 3

_LABEL_LEAD_MONTHS = 6

_GROWTH_LOOKBACK = pd.Timedelta(days=730)
_HISTORY_LOOKBACK = pd.DateOffset(years=6)

_HISTORY_CHANGE_FIELDS = {
    "gross_profitability_change_5y": "gross_profitability",
    "roa_change_5y": "roa",
    "roic_change_5y": "roic",
    "cfo_to_assets_change_5y": "cfo_to_assets",
    "grossmargin_change_5y": "grossmargin",
    "de_change_5y": "de",
}

_HISTORY_VOLATILITY_FIELDS = {
    "roe_volatility_5y": "roe",
    "grossmargin_volatility_5y": "grossmargin",
}


class FundamentalSignals(Signals):
    """SQL-backed fundamental facts with opt-in DataFrame attachments.

    ``get_signals`` fetches the latest ART row per ticker; ``attach_ratios``,
    ``attach_growth``, and ``attach_history_features`` add derived columns to a
    ticker-indexed frame. Every method is stateless.
    """

    @classmethod
    def get_signals(
        cls,
        tickers: list[str] | None,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Return each ticker's latest ART filing published by the signal day.

        Passing ``tickers`` preserves the caller's order and silently drops
        names with no filing at all. Return a ticker-indexed frame, empty with
        no columns when the date predates the stored fundamentals.
        """
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
        """Attach year-over-year growth facts from the quarterly series.

        Compares the newest ARQ period against the one five quarters earlier, so
        a ticker with fewer than five published quarters gets nulls rather than
        a shorter comparison. Return a copy of ``frame`` with the growth columns
        joined on.
        """
        frame = frame.copy()
        arq = cls._as_of_filings(
            frame.index.astype(str).tolist(),
            "ARQ",
            pd.Timestamp(signal_day),
            _GROWTH_LOOKBACK,
        )
        return frame.join(cls._calculate_growth(arq), how="left")

    @classmethod
    def attach_history_features(
        cls,
        frame: pd.DataFrame,
        signal_day: pd.Timestamp,
    ) -> pd.DataFrame:
        """Attach five-year change, volatility, and history-sufficiency facts.

        Built from the annual series, so these columns need roughly six years of
        filings before they resolve and are largely null in early backtest
        windows. ``complete_multi_year_history`` records whether the window was
        deep enough to trust. Return a copy of ``frame`` with them joined on.
        """
        frame = frame.copy()
        annual_history = cls._as_of_filings(
            frame.index.astype(str).tolist(),
            "ARY",
            pd.Timestamp(signal_day),
            _HISTORY_LOOKBACK,
        )
        history = cls._calculate_history_features(annual_history)
        return frame.join(history, how="left")

    @classmethod
    def attach_ratios(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach ratios that combine several stored fundamental columns.

        Ratios whose sign would be meaningless are left null rather than
        computed: a yield is only taken against a positive market cap. Return a
        copy of ``frame`` with the ratio columns added.
        """
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
    def _as_of_filings(
        cls,
        tickers: list[str],
        dimension: str,
        signal_day: pd.Timestamp,
        lookback,
    ) -> pd.DataFrame:
        """Return rows of ``dimension`` covering ``lookback`` and published by now.

        ``lookback`` is any span subtractable from a Timestamp, so a caller can
        pass calendar days or calendar years as the accounting period requires.

        The repository filters on ``calendardate``, so the query window is
        padded forward by ``_LABEL_LEAD_MONTHS`` to reach periods that had
        already closed on the signal day, and ``datekey`` then discards whatever
        had not actually been published yet.

        Both halves are load-bearing and only one of them is obvious. Without
        the pad the newest period is missed and every fact lags a quarter.
        Without the ``datekey`` filter the caller reads reports that did not
        exist on the signal day, which is lookahead that surfaces as skill
        rather than as an error, because next quarter's earnings really do
        predict next quarter's returns.
        """
        frame = fundamentals_repo.get(
            tickers=tickers,
            dimension=dimension,
            start_date=str((signal_day - lookback).date()),
            end_date=str(
                (signal_day + pd.DateOffset(months=_LABEL_LEAD_MONTHS)).date()
            ),
        )
        if frame.empty:
            return frame
        return frame[pd.to_datetime(frame["datekey"]) <= signal_day]

    @classmethod
    def _calculate_growth(cls, arq: pd.DataFrame) -> pd.DataFrame:
        """Reduce a quarterly series to one year-over-year row per ticker.

        Tickers with fewer than five published quarters are omitted entirely
        rather than compared over a shorter span.
        """
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
        """Reduce an annual series to five-year change and volatility rows.

        The window is measured back from each ticker's own latest period rather
        than from a shared date, so a late filer is not penalised. Changes and
        volatilities are null unless the window holds enough observations to
        mean anything.
        """
        if ary.empty:
            return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))

        ary = ary.copy()
        ary["gross_profitability"] = cls.safe_div(ary["gp"], ary["assets"])
        ary["cfo_to_assets"] = cls.safe_div(ary["ncfo"], ary["assets"])
        ary["calendardate"] = pd.to_datetime(ary["calendardate"])
        ary["datekey"] = pd.to_datetime(ary["datekey"])

        ary = ary.dropna(subset=["calendardate"])
        if ary.empty:
            return pd.DataFrame(columns=list(QUALITY_HISTORY_COLUMNS))

        ary = ary.sort_values(["ticker", "calendardate", "datekey"])
        ary = ary.drop_duplicates(["ticker", "calendardate"], keep="last")

        latest_period = ary.groupby("ticker")["calendardate"].transform("last")
        distinct = pd.DatetimeIndex(latest_period.unique())
        cutoffs = pd.Series(
            distinct - pd.DateOffset(years=QUALITY_HISTORY_TARGET_YEARS),
            index=distinct,
        )
        window = ary[ary["calendardate"] >= latest_period.map(cutoffs)]

        by_ticker = window.groupby("ticker", sort=True)
        observations = by_ticker.size()
        complete = observations >= MIN_QUALITY_HISTORY_OBSERVATIONS

        earliest = window.groupby("ticker", sort=True).head(1).set_index("ticker")
        latest = window.groupby("ticker", sort=True).tail(1).set_index("ticker")

        features = pd.DataFrame(index=observations.index)
        for name, column in _HISTORY_CHANGE_FIELDS.items():
            features[name] = (latest[column] - earliest[column]).where(complete)

        then = earliest["shareswa"]
        features["share_dilution_5y"] = (
            ((latest["shareswa"] - then) / then.abs()).where(then != 0).where(complete)
        )

        for name, column in _HISTORY_VOLATILITY_FIELDS.items():
            values = pd.to_numeric(window[column], errors="coerce")
            grouped = values.groupby(window["ticker"], sort=True)
            features[name] = (
                grouped.std(ddof=0)
                .where(grouped.count() >= MIN_VOLATILITY_OBSERVATIONS)
                .where(complete)
            )

        features["quality_history_observations"] = observations
        features["complete_multi_year_history"] = complete
        features.index.name = "ticker"
        return features[list(QUALITY_HISTORY_COLUMNS)]

    @staticmethod
    def _history_change(latest, prior, complete_history, column) -> float:
        """Return the change in ``column``, or NaN if the history is too thin."""
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
        """Return the dispersion of ``column``, or NaN if the history is thin."""
        if not complete_history:
            return np.nan
        values = pd.to_numeric(window[column], errors="coerce").dropna()
        if len(values) < 3:
            return np.nan
        return values.std(ddof=0)
