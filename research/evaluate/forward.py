"""Forward returns over a fixed horizon of market sessions.

The measurement half of a walk-forward. The window closes on an exact session
from ``research.calendar``, so every name spans the identical wall clock.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

import research.calendar as calendar
from database.db_connection import get_connection

_PRICE_COLUMN = "closeadj"

_EQUITY_TABLE = "equity_prices"
_FUND_TABLE = "fund_prices"

_MIN_HORIZON_SESSIONS = 2

_QUERY_TEMPLATE = """
    WITH ranked AS (
        SELECT
            ticker,
            date,
            {price} AS price,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date) AS n,
            COUNT(*)     OVER (PARTITION BY ticker)               AS observed
        FROM {table}
        WHERE ticker = ANY(:tickers)
          AND date >  CAST(:as_of AS date)
          AND date <= CAST(:window_end AS date)
          AND {price} > 0
    )
    SELECT
        ticker,
        MAX(CASE WHEN n = 1 THEN date  END)  AS entry_date,
        MAX(CASE WHEN n = 1 THEN price END)  AS entry_price,
        MAX(CASE WHEN n = LEAST(:horizon, observed) THEN date  END) AS exit_date,
        MAX(CASE WHEN n = LEAST(:horizon, observed) THEN price END) AS exit_price,
        LEAST(:horizon, MAX(observed))       AS sessions_held,
        (MAX(observed) >= :horizon)          AS complete
    FROM ranked
    GROUP BY ticker
    HAVING MAX(CASE WHEN n = 1 THEN price END) IS NOT NULL
    ORDER BY ticker
"""


_PANEL_TEMPLATE = """
    SELECT ticker, date, {price} AS price
    FROM {table}
    WHERE ticker = ANY(:tickers)
      AND date >  CAST(:as_of AS date)
      AND date <= CAST(:window_end AS date)
      AND {price} > 0
    ORDER BY ticker, date
"""


class ForwardReturns:
    """Return from the first session after the signal day to a fixed horizon.

    The horizon counts market sessions, not each security's own bars: a name
    that halts or delists exits on its last bar and reports ``complete=False``.
    Counting its own bars instead would let a sparse security's "252 sessions"
    span fourteen months against a liquid one's twelve.
    """

    def __init__(self, horizon_sessions: int = 252) -> None:
        """Set the horizon in market sessions.

        :raises ValueError: below ``_MIN_HORIZON_SESSIONS``, since an entry and
            an exit cannot come from the same bar.
        """
        if horizon_sessions < _MIN_HORIZON_SESSIONS:
            raise ValueError(
                f"horizon_sessions must be at least {_MIN_HORIZON_SESSIONS} "
            )
        self.horizon_sessions = horizon_sessions

    def __repr__(self) -> str:
        """Return the configured horizon."""
        return f"ForwardReturns(horizon_sessions={self.horizon_sessions})"

    def run(self, tickers, signal_day) -> pd.DataFrame:
        """Return forward returns for equities over the horizon."""
        return self._returns(_EQUITY_TABLE, tickers, signal_day)

    def benchmark(self, tickers, signal_day) -> pd.DataFrame:
        """Return forward returns for funds, read from the fund price table."""
        return self._returns(_FUND_TABLE, tickers, signal_day)

    def _returns(self, table: str, tickers, signal_day) -> pd.DataFrame:
        """Measure one population over the horizon against ``table``.

        :returns: one row per measurable ticker with entry/exit dates and
            prices, ``forward_return``, ``sessions_held``, and ``complete``. A
            ticker with no price after the signal day is absent, not null.
        """
        # Clamping to the end of the data is what lets an unfinished horizon
        # report complete=False rather than raise.
        query = text(_QUERY_TEMPLATE.format(table=table, price=_PRICE_COLUMN))
        window_end = calendar.horizon_end(signal_day, self.horizon_sessions)
        frame = pd.read_sql_query(
            query,
            get_connection(),
            params={
                "tickers": list(tickers),
                "as_of": pd.Timestamp(signal_day).date().isoformat(),
                "horizon": self.horizon_sessions,
                "window_end": window_end.isoformat(),
            },
        )
        frame["forward_return"] = frame["exit_price"] / frame["entry_price"] - 1
        frame["signal_day"] = pd.Timestamp(signal_day).date()
        return frame[
            [
                "ticker",
                "signal_day",
                "entry_date",
                "entry_price",
                "exit_date",
                "exit_price",
                "forward_return",
                "sessions_held",
                "complete",
            ]
        ]

    def panel(self, tickers, signal_day) -> pd.DataFrame:
        """Return each security's daily returns across the horizon.

        The window ``run`` measures, kept as a series rather than collapsed to
        one number: a correlation needs the periods behind a return.

        :returns: sessions x tickers of simple returns, aligned on the session
            grid so a halted name carries NaN rather than shifting its
            neighbours' dates. A ticker with no price in the window is absent.
        """
        query = text(_PANEL_TEMPLATE.format(table=_EQUITY_TABLE, price=_PRICE_COLUMN))
        window_end = calendar.horizon_end(signal_day, self.horizon_sessions)
        frame = pd.read_sql_query(
            query,
            get_connection(),
            params={
                "tickers": list(tickers),
                "as_of": pd.Timestamp(signal_day).date().isoformat(),
                "window_end": window_end.isoformat(),
            },
        )
        if frame.empty:
            return pd.DataFrame()
        prices = frame.pivot(index="date", columns="ticker", values="price")
        return prices.sort_index().pct_change().iloc[1:]
