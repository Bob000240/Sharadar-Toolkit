"""The structural universe: which securities exist and are tradable at all.

These are the non-negotiable listing rules — security type, exchange, and
recency of trading — as distinct from the elective filters a strategy chooses.
A screen composes both, but only this half decides whether a security is a
candidate in principle.

Recency is enforced against the last date the security actually produced a
price, read per ticker by a lateral join, so a name that quietly stopped
trading drops out before any strategy sees it. ``_STALE_TRADE_DAYS`` is the
threshold past which that guarantee weakens enough to warrant a warning.
"""

from __future__ import annotations

import warnings

import pandas as pd
from sqlalchemy import text

from database.db_connection import get_connection

_CATEGORIES_BY_SECURITY_TYPE: dict[str, tuple[str, ...]] = {
    "common_stock": (
        "Domestic Common Stock",
        "Domestic Common Stock Primary Class",
        "Canadian Common Stock",
        "Canadian Common Stock Primary Class",
        "ADR Common Stock",
        "ADR Common Stock Primary Class",
    ),
    "preferred_stock": (
        "Domestic Preferred Stock",
        "ADR Preferred Stock",
        "Canadian Preferred Stock",
    ),
    "warrant": (
        "Domestic Common Stock Warrant",
        "ADR Common Stock Warrant",
        "Canadian Common Stock Warrant",
    ),
}

_EXCHANGES = ("NYSE", "NASDAQ", "NYSEMKT", "NYSEARCA", "BATS", "OTC")

_EQUITY_TABLE_CODE = "SEP"

_MAX_RECENT_TRADE_DAYS = 30
_STALE_TRADE_DAYS = 10

_QUERY = text("""
    SELECT
        t.ticker,
        t.permaticker,
        t.name,
        t.exchange,
        t.category,
        t.currency,
        t.famaindustry,
        recency.last_traded
    FROM tickers AS t
    JOIN LATERAL (
        SELECT ep.date AS last_traded
        FROM equity_prices AS ep
        WHERE ep.ticker = t.ticker
          AND ep.date <= CAST(:as_of AS date)
        ORDER BY ep.date DESC
        LIMIT 1
    ) AS recency ON TRUE
    WHERE t.table_code = :table_code
      AND (
            (t.category = ANY(:categories) AND t.exchange = ANY(:exchanges))
            OR t.ticker = ANY(:include_tickers)
          )
      AND NOT (t.ticker = ANY(:exclude_tickers))
      AND recency.last_traded
          >= CAST(:as_of AS date) - CAST(:recent_trade_days AS integer)
    ORDER BY t.ticker
""")


class Universe:
    """A point-in-time list of securities eligible on structural grounds.

    The only public method is ``run``, which issues the query for one signal
    day. Instance variables mirror the constructor arguments: ``security_types``,
    ``exchanges``, ``include_tickers``, ``exclude_tickers``, and
    ``recent_trade_days``.

    Stateless with respect to the signal day, so one instance is built once and
    reused across every date of a sweep.
    """

    def __init__(
        self,
        security_types: tuple[str, ...] = ("common_stock",),
        exchanges: tuple[str, ...] = ("NYSE", "NASDAQ"),
        include_tickers: tuple[str, ...] = (),
        exclude_tickers: tuple[str, ...] = (),
        recent_trade_days: int = 10,
    ) -> None:
        """Resolve the requested security types to categories and validate.

        ``include_tickers`` are admitted regardless of category and exchange;
        ``exclude_tickers`` are removed regardless of everything else.
        ``recent_trade_days`` is the tolerated gap since the security last
        traded. Validation runs here rather than at query time, so a malformed
        universe cannot reach the database. Raise ValueError for an empty or
        unregistered security type or exchange, or an out-of-range recency.
        """
        self.security_types = tuple(security_types)
        self.exchanges = tuple(exchanges)
        self.include_tickers = tuple(include_tickers)
        self.exclude_tickers = tuple(exclude_tickers)
        self.recent_trade_days = recent_trade_days

        self._categories = self._resolve_categories()
        self._validate_exchanges()
        self._validate_recency()

    def __repr__(self) -> str:
        """Return every setting that affects membership."""
        return (
            f"Universe(security_types={self.security_types}, "
            f"exchanges={self.exchanges}, "
            f"include_tickers={self.include_tickers}, "
            f"exclude_tickers={self.exclude_tickers}, "
            f"recent_trade_days={self.recent_trade_days})"
        )

    def _resolve_categories(self) -> list[str]:
        """Expand the requested security types into Sharadar category names.

        Return the sorted union of their categories. Raise ValueError when no
        type is given or a type is not registered.
        """
        if not self.security_types:
            raise ValueError("security_types must not be empty")
        unknown = tuple(
            t for t in self.security_types if t not in _CATEGORIES_BY_SECURITY_TYPE
        )
        if unknown:
            raise ValueError(
                f"unregistered security_types {unknown}; registered types are "
                f"{tuple(_CATEGORIES_BY_SECURITY_TYPE)}"
            )
        return sorted(
            {c for t in self.security_types for c in _CATEGORIES_BY_SECURITY_TYPE[t]}
        )

    def _validate_exchanges(self) -> None:
        """Raise ValueError when no exchange is given or a code is unknown."""
        if not self.exchanges:
            raise ValueError("exchanges must not be empty")
        unknown = tuple(e for e in self.exchanges if e not in _EXCHANGES)
        if unknown:
            raise ValueError(
                f"unregistered exchanges {unknown}; registered codes are {_EXCHANGES}"
            )

    def _validate_recency(self) -> None:
        """Bound the tolerated trading gap and warn when it grows stale.

        Raise ValueError outside [1, ``_MAX_RECENT_TRADE_DAYS``]. Beyond
        ``_STALE_TRADE_DAYS`` the population starts admitting securities that
        have stopped trading but are not yet delisted, which is a warning rather
        than an error because a wider window is sometimes wanted deliberately.
        """
        if not 1 <= self.recent_trade_days <= _MAX_RECENT_TRADE_DAYS:
            raise ValueError(
                f"recent_trade_days must be between 1 and {_MAX_RECENT_TRADE_DAYS}; "
                f"got {self.recent_trade_days}"
            )
        if self.recent_trade_days > _STALE_TRADE_DAYS:
            warnings.warn(
                f"recent_trade_days={self.recent_trade_days} exceeds "
                f"{_STALE_TRADE_DAYS}; the population may include securities that "
                "have stopped trading but are not yet delisted",
                stacklevel=3,
            )

    def run(self, signal_day) -> pd.DataFrame:
        """Return the securities eligible as of ``signal_day``.

        ``signal_day`` is treated as an as-of date, so it need not be a trading
        session, though callers that align it first get an honest one.

        Return one row per security with its ticker, permaticker, name,
        exchange, category, currency, Fama industry, and the date it last
        traded.
        """
        return pd.read_sql_query(
            _QUERY,
            get_connection(),
            params={
                "as_of": pd.Timestamp(signal_day).date().isoformat(),
                "table_code": _EQUITY_TABLE_CODE,
                "categories": self._categories,
                "exchanges": list(self.exchanges),
                "include_tickers": list(self.include_tickers),
                "exclude_tickers": list(self.exclude_tickers),
                "recent_trade_days": self.recent_trade_days,
            },
        )


def unmapped_categories() -> list[str]:
    """Return the ticker categories no registered security type claims.

    A maintenance aid: Sharadar adds categories over time, and one that nothing
    maps to is silently absent from every universe.
    """
    known = pd.read_sql_query(
        text("SELECT DISTINCT category FROM tickers WHERE category IS NOT NULL"),
        get_connection(),
    )
    claimed = {c for group in _CATEGORIES_BY_SECURITY_TYPE.values() for c in group}
    return sorted(set(known["category"]) - claimed)
