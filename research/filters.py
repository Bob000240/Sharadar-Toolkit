from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from database.db_connection import get_connection

_OPERATORS = {
    ">=": lambda series, value: series >= value,
    ">": lambda series, value: series > value,
    "<=": lambda series, value: series <= value,
    "<": lambda series, value: series < value,
    "==": lambda series, value: series == value,
    "!=": lambda series, value: series != value,
}


class Filters:
    def __init__(self, *conditions: tuple[str, str, object]) -> None:
        self.conditions = conditions
        self._validate()

    def __repr__(self) -> str:
        return f"Filters({', '.join(str(c) for c in self.conditions)})"

    def _validate(self) -> None:
        if not self.conditions:
            raise ValueError("Filters requires at least one condition")
        unknown = {op for _, op, _ in self.conditions if op not in _OPERATORS}
        if unknown:
            raise ValueError(
                f"unregistered operators {unknown}; registered operators are "
                f"{tuple(_OPERATORS)}"
            )

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        survivors = frame
        for field, operator, value in self.conditions:
            survivors = survivors[_OPERATORS[operator](survivors[field], value)]
        return survivors

    def funnel(self, frame: pd.DataFrame) -> pd.DataFrame:
        rows = []
        survivors = frame
        for field, operator, value in self.conditions:
            before = len(survivors)
            null_count = int(survivors[field].isna().sum())
            survivors = survivors[_OPERATORS[operator](survivors[field], value)]
            after = len(survivors)
            rows.append(
                {
                    "condition": f"{field} {operator} {value}",
                    "before": before,
                    "after": after,
                    "dropped": before - after,
                    "dropped_for_null": null_count,
                }
            )
        return pd.DataFrame(rows)


_FUNDAMENTALS_QUERY = text("""
    SELECT DISTINCT ON (ticker) ticker, marketcap, netinccmnusd
    FROM fundamentals
    WHERE dimension = 'ART'
      AND datekey <= CAST(:as_of AS date)
      AND marketcap > 0
    ORDER BY ticker, datekey DESC
""")


def attach_fundamentals(frame: pd.DataFrame, signal_day) -> pd.DataFrame:
    facts = pd.read_sql_query(
        _FUNDAMENTALS_QUERY,
        get_connection(),
        params={"as_of": pd.Timestamp(signal_day).date().isoformat()},
    )
    return frame.merge(facts, on="ticker", how="left")


if __name__ == "__main__":
    from research.evaluate.forward import ForwardReturns
    from research.evaluate.walk_forward import WalkForward
    from research.universe import Universe

    SIGNAL_DAY = "2024-06-14"
    universe = Universe()
    base = universe.run(SIGNAL_DAY)
    priced = attach_fundamentals(base, SIGNAL_DAY)

    print(f"\nFUNDAMENTALS COVERAGE on {SIGNAL_DAY}")
    print(f"  universe          {len(base):,}")
    print(f"  with marketcap    {priced.marketcap.notna().sum():,}")
    print(f"  null marketcap    {priced.marketcap.isna().sum():,}")

    print(f"\nFUNNEL on {SIGNAL_DAY} — the $1B vs $10B question in eligibility_repo.py")
    for label, floor in (
        ("documented: market_cap_min_1b", 1_000_000_000),
        ("implemented: _SL_MIN_MARKET_CAP = $10B", 10_000_000_000),
    ):
        print(f"\n  {label}")
        funnel = Filters(("marketcap", ">=", floor)).funnel(priced)
        print(funnel.to_string(index=False))

    SIGNAL_DAYS = pd.date_range("2016-01-01", "2025-01-01", freq="QS").tolist()
    forward = ForwardReturns(horizon_sessions=252)
    walk = WalkForward(universe, forward, benchmark="SPY")

    print(
        f"\nWALK-FORWARD: does a market-cap floor close the gap? ({len(SIGNAL_DAYS)} quarters)"
    )

    def _make_population(floor):
        def _population(day):
            pop = attach_fundamentals(universe.run(day), day)
            if floor is not None:
                pop = Filters(("marketcap", ">=", floor)).apply(pop)
            return pop.ticker

        return _population

    for label, floor in (
        ("no filter (baseline)", None),
        ("$1B floor", 1_000_000_000),
        ("$10B floor", 10_000_000_000),
    ):
        by_date = walk.run(SIGNAL_DAYS, population=_make_population(floor))
        summary = WalkForward.summarize(by_date)
        print(
            f"  {label:<22} n(median)={by_date.n.median():>6.0f}   "
            f"median excess {summary['median_excess']:+.2%}   "
            f"dates beat bench {summary['pct_dates_beat_benchmark']:.1%}"
        )
