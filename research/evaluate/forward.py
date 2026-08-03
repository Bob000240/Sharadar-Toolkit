from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from database.db_connection import get_connection

_PRICE_COLUMN = "closeadj"

_EQUITY_TABLE = "equity_prices"
_FUND_TABLE = "fund_prices"

_MIN_HORIZON_SESSIONS = 2

_CALENDAR_SLACK = 1.7
_CALENDAR_PAD = 15

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
          AND date <= CAST(:as_of AS date) + CAST(:calendar_window AS integer)
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


class ForwardReturns:
    def __init__(self, horizon_sessions: int = 252) -> None:
        if horizon_sessions < _MIN_HORIZON_SESSIONS:
            raise ValueError(
                f"horizon_sessions must be at least {_MIN_HORIZON_SESSIONS} "
            )
        self.horizon_sessions = horizon_sessions
        self._calendar_window = int(horizon_sessions * _CALENDAR_SLACK) + _CALENDAR_PAD

    def __repr__(self) -> str:
        return f"ForwardReturns(horizon_sessions={self.horizon_sessions})"

    # ── execution ────────────────────────────────────────────────────────────

    def run(self, tickers, signal_day) -> pd.DataFrame:
        return self._returns(_EQUITY_TABLE, tickers, signal_day)

    def benchmark(self, tickers, signal_day) -> pd.DataFrame:
        return self._returns(_FUND_TABLE, tickers, signal_day)

    def _returns(self, table: str, tickers, signal_day) -> pd.DataFrame:
        query = text(_QUERY_TEMPLATE.format(table=table, price=_PRICE_COLUMN))
        frame = pd.read_sql_query(
            query,
            get_connection(),
            params={
                "tickers": list(tickers),
                "as_of": pd.Timestamp(signal_day).date().isoformat(),
                "horizon": self.horizon_sessions,
                "calendar_window": self._calendar_window,
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
