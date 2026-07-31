"""The structural security population as of a point in time.

A `Universe` answers one question: which securities existed, were listed where
you asked, and were actually trading on `signal_day`. It answers nothing about
whether any of them are attractive — no size floor, no profitability, no
liquidity, no trend. Those are filters, and keeping them out is what makes
"filtered population versus structural population" a measurable comparison.

Every row is constrained to information visible on or before `signal_day`.
"""

from __future__ import annotations

import warnings

import pandas as pd
from sqlalchemy import text

from database.db_connection import get_connection

# Vendor `tickers.category` fuses instrument, filing regime, and share class
# into one string. These are the 16 values it takes, grouped by the instrument
# each represents. Listed exhaustively rather than pattern-matched so a category
# the vendor adds later surfaces through `unmapped_categories()` instead of
# being silently mis-split.
#
# A security type is the *instrument* — what claim you hold — and nothing else.
# Every type below spans all three filing regimes (Domestic, ADR, Canadian),
# because regime is a different axis and folding one into this one made `adr`
# mean "ADR common stock only" while preferred and warrants quietly ignored it.
#
# Regime still matters, but as a fact to filter on rather than a definition:
# insider coverage is 43.5% of domestic filers, 39.3% of ADRs, and 8.1% of
# Canadian MJDS filers, so a screen leaning on insider activity is evaluating
# near-empty data across part of this population. That belongs in the funnel
# where it can be measured, not baked into the denominator.
#
# Secondary share classes belong to no type on purpose: they are the second
# listing of an issuer already present (GOOG beside GOOGL), so admitting them
# double-counts one company in any percentile or per-group cut. This matches the
# `category NOT LIKE '%Secondary%'` rule in eligibility_repo.
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

# `etf` and `closed_end_fund` are absent rather than registered-and-empty. A
# type only earns registration once its source coverage is validated, and
# neither one clears that bar through this query: the master holds no closed-end
# funds at all, and funds sit in table_code 'SFP' with their prices in
# `fund_prices`, so an ETF can never satisfy the SEP filter or the
# `equity_prices` recency join. Registering a type that always returns zero rows
# would be worse than an unknown-type error, which at least says why.
#
# Fund research is a real follow-on, not a flag: it needs the SFP ticker set
# loaded, `technical_features` extended to cover `fund_prices` (it has zero fund
# rows today, so there is nothing to rank a fund on), and only then a price-table
# parameter here.

# Registered exchange codes. OTC is selectable but never a default, so reaching
# it always takes an explicit choice.
_EXCHANGES = ("NYSE", "NASDAQ", "NYSEMKT", "NYSEARCA", "BATS", "OTC")

# Equities live in Sharadar's SEP table; SFP holds funds.
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

    # ── validation, paid once at construction ────────────────────────────────

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

    # ── execution ────────────────────────────────────────────────────────────

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
    """Category strings in the security master that no security type claims.

    Expect exactly four: the three secondary share classes, and `ETF`. All are
    unclaimed on purpose. Anything else means the vendor introduced a category
    and those securities are unreachable by any argument.
    """
    known = pd.read_sql_query(
        text("SELECT DISTINCT category FROM tickers WHERE category IS NOT NULL"),
        get_connection(),
    )
    claimed = {c for group in _CATEGORIES_BY_SECURITY_TYPE.values() for c in group}
    return sorted(set(known["category"]) - claimed)


if __name__ == "__main__":
    EARLY, LATE = "2018-06-15", "2024-06-14"

    def _show(label: str, frame: pd.DataFrame) -> None:
        print(f"  {label:<44}{len(frame):>7,}")

    # ── security-master health ───────────────────────────────────────────────
    # Only the three secondary share classes are expected to go unclaimed.
    print("\nUNCLAIMED CATEGORIES")
    for category in unmapped_categories():
        print(f"  {category}")

    # ── the default population ───────────────────────────────────────────────
    default = Universe()
    print(f"\nDEFAULTS on {LATE}\n  {default!r}")
    base = default.run(LATE)
    print(base.head(6).to_string(index=False))
    print(f"\n  exchange      {dict(base['exchange'].value_counts())}")
    print(f"  category      {dict(base['category'].value_counts())}")
    print(f"  issuers       {base.permaticker.nunique():,} distinct permatickers")
    print(f"  famaindustry  {base['famaindustry'].isna().sum()} null")

    # ── point-in-time membership ─────────────────────────────────────────────
    # One definition, many dates — the shape a walk-forward needs. Counts must
    # move; a flat line means the recency join is inert and this is really a
    # static list wearing a date parameter.
    print("\nONE UNIVERSE, DIFFERENT DATES")
    early = default.run(EARLY)
    _show(EARLY, early)
    for day in ("2021-03-15", "2026-07-20"):
        _show(day, default.run(day))
    _show(LATE, base)

    # ── survivorship ─────────────────────────────────────────────────────────
    # Membership follows trading activity, never the `isdelisted` flag, so names
    # that died between the two dates stay in the earlier population.
    departed = sorted(set(early.ticker) - set(base.ticker))
    print(f"\nSURVIVORSHIP  {EARLY} -> {LATE}")
    _show("left the universe (delisted / acquired)", pd.DataFrame(departed))
    _show(
        "entered the universe (IPO / relisting)",
        pd.DataFrame(set(base.ticker) - set(early.ticker)),
    )
    print(f"  sample of the departed: {', '.join(departed[:10])}")

    # ── security_types ───────────────────────────────────────────────────────
    # Each type is one instrument spanning all three filing regimes, so these
    # deltas are the cost of admitting a different kind of claim — not a
    # different kind of issuer.
    print(f"\nsecurity_types on {LATE}")
    _show("common_stock (default)", base)
    for types in [
        ("common_stock", "preferred_stock"),
        ("common_stock", "warrant"),
        ("common_stock", "preferred_stock", "warrant"),
        ("preferred_stock",),
    ]:
        _show(str(types), Universe(security_types=types).run(LATE))

    # ── exchanges ────────────────────────────────────────────────────────────
    # OTC is reachable but never a default, so it always takes a deliberate ask.
    print(f"\nexchanges on {LATE}")
    _show("NYSE + NASDAQ (default)", base)
    for venues in [("NYSE",), ("NASDAQ",), ("NYSE", "NASDAQ", "NYSEMKT"), ("OTC",)]:
        _show(str(venues), Universe(exchanges=venues).run(LATE))

    # ── explicit include / exclude ───────────────────────────────────────────
    # `include_tickers` admits a symbol the categorical arguments reject, but
    # never waives the recency guard; `exclude_tickers` wins over it.
    guest = Universe(security_types=("preferred_stock",)).run(LATE).ticker.iloc[0]
    print(f"\nINCLUDE / EXCLUDE on {LATE}  (guest = {guest}, a preferred issue)")
    _show("default", base)
    _show(f"include ({guest},)", Universe(include_tickers=(guest,)).run(LATE))
    _show("exclude (AAPL, MSFT)", Universe(exclude_tickers=("AAPL", "MSFT")).run(LATE))
    _show(
        f"include and exclude {guest}",
        Universe(include_tickers=(guest,), exclude_tickers=(guest,)).run(LATE),
    )

    # ── staleness tolerance ──────────────────────────────────────────────────
    # Calendar days, so the window spans weekends and holidays. Anything looser
    # than 10 warns at construction, because it readmits securities that have
    # stopped trading.
    print(f"\nrecent_trade_days on {LATE}")
    for days in (1, 10, 30):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            universe = Universe(recent_trade_days=days)
        _show(
            f"{days} calendar days{'  [warns]' if caught else ''}", universe.run(LATE)
        )

    # ── rejected arguments ───────────────────────────────────────────────────
    # Validation runs at construction, before any query. A typo costs nothing,
    # and an empty result always means "no securities matched", never "you
    # misspelled it".
    print("\nREJECTED AT CONSTRUCTION")
    for label, kwargs in (
        ("unregistered type", dict(security_types=("closed_end_fund",))),
        ("unregistered exchange", dict(exchanges=("NYSEAMEX",))),
        ("empty types", dict(security_types=())),
        ("out of range", dict(recent_trade_days=0)),
    ):
        try:
            Universe(**kwargs)
            print(f"  {label:<24}NOT REJECTED — validation gap")
        except ValueError as error:
            print(f"  {label:<24}{error}")
    print(default.run(LATE).head(6).to_string(index=False))
