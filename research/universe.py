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
    def __init__(
        self,
        security_types: tuple[str, ...] = ("common_stock",),
        exchanges: tuple[str, ...] = ("NYSE", "NASDAQ"),
        include_tickers: tuple[str, ...] = (),
        exclude_tickers: tuple[str, ...] = (),
        recent_trade_days: int = 10,
    ) -> None:
        self.security_types = tuple(security_types)
        self.exchanges = tuple(exchanges)
        self.include_tickers = tuple(include_tickers)
        self.exclude_tickers = tuple(exclude_tickers)
        self.recent_trade_days = recent_trade_days

        self._categories = self._resolve_categories()
        self._validate_exchanges()
        self._validate_recency()

    def __repr__(self) -> str:
        return (
            f"Universe(security_types={self.security_types}, "
            f"exchanges={self.exchanges}, "
            f"include_tickers={self.include_tickers}, "
            f"exclude_tickers={self.exclude_tickers}, "
            f"recent_trade_days={self.recent_trade_days})"
        )

    def _resolve_categories(self) -> list[str]:
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
        if not self.exchanges:
            raise ValueError("exchanges must not be empty")
        unknown = tuple(e for e in self.exchanges if e not in _EXCHANGES)
        if unknown:
            raise ValueError(
                f"unregistered exchanges {unknown}; registered codes are {_EXCHANGES}"
            )

    def _validate_recency(self) -> None:
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
    known = pd.read_sql_query(
        text("SELECT DISTINCT category FROM tickers WHERE category IS NOT NULL"),
        get_connection(),
    )
    claimed = {c for group in _CATEGORIES_BY_SECURITY_TYPE.values() for c in group}
    return sorted(set(known["category"]) - claimed)
