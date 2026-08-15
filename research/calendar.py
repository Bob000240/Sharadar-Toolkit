"""Trading sessions, as observed in the price data.

A *session* is a date on which the equity market produced prices. This module is
the single authority on that question, so callers stop approximating it — no
weekday arithmetic, no calendar-day fudge factors, no assuming the date handed
to a screen is a day the market was actually open.

The session list is read once and cached for the life of the process. Call
`refresh()` after a daily update if a long-running process needs to see dates
loaded since it started.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import text

from database.db_connection import get_connection

_SESSION_TABLE = "equity_prices"

_QUERY = text(f"SELECT DISTINCT date FROM {_SESSION_TABLE} ORDER BY date")

_sessions: pd.DatetimeIndex | None = None


def sessions() -> pd.DatetimeIndex:
    """Every session on record, ascending. Cached after the first call."""
    global _sessions
    if _sessions is None:
        frame = pd.read_sql_query(_QUERY, get_connection())
        if frame.empty:
            raise RuntimeError(
                f"{_SESSION_TABLE} contains no dates; load price data before "
                "using the trading calendar"
            )
        _sessions = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    return _sessions


def refresh() -> None:
    """Drop the cached session list so the next call re-reads the database."""
    global _sessions
    _sessions = None


def _stamp(day) -> pd.Timestamp:
    return pd.Timestamp(day).normalize()


def _out_of_range(day: pd.Timestamp) -> str:
    known = sessions()
    return (
        f"{day.date()} lies outside the loaded calendar "
        f"({known[0].date()} to {known[-1].date()})"
    )


def first_session() -> date:
    """Earliest session on record."""
    return sessions()[0].date()


def last_session() -> date:
    """Latest session on record. This is the newest date the data can support,
    which is not necessarily the latest session the market has held."""
    return sessions()[-1].date()


def is_session(day) -> bool:
    """True if the market produced prices on `day`."""
    return _stamp(day) in sessions()


def align(day) -> date:
    """The latest session on or before `day` — the honest as-of date for a
    request made on `day`. Raises if `day` precedes the first session; a `day`
    past the end of the data aligns to the last session on record.
    """
    known = sessions()
    stamp = _stamp(day)
    position = known.searchsorted(stamp, side="right") - 1
    if position < 0:
        raise ValueError(_out_of_range(stamp))
    return known[position].date()


def align_forward(day) -> date:
    """The earliest session on or after `day` — the opening session of a period
    that begins on `day`. The mirror of `align`, which looks backward for an
    as-of date. Raises if the data does not reach `day`.
    """
    known = sessions()
    stamp = _stamp(day)
    position = known.searchsorted(stamp, side="left")
    if position >= len(known):
        raise ValueError(_out_of_range(stamp))
    return known[position].date()


def latest_session(as_of=None) -> date:
    """The session a screen run at `as_of` (default today) should use. Alias for
    `align` that reads better at call sites deciding *when* to run."""
    return align(date.today() if as_of is None else as_of)


def next_session(day, count: int = 1) -> date:
    """The `count`-th session strictly after `day`.

    Raises if the data does not extend that far — use `horizon_end` where
    running off the end of the data is expected rather than exceptional.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1; got {count}")
    known = sessions()
    stamp = _stamp(day)
    position = known.searchsorted(stamp, side="right") + count - 1
    if position >= len(known):
        raise ValueError(
            f"only {len(known) - known.searchsorted(stamp, side='right')} "
            f"session(s) follow {stamp.date()}; cannot advance {count}"
        )
    return known[position].date()


def previous_session(day, count: int = 1) -> date:
    """The `count`-th session strictly before `day`."""
    if count < 1:
        raise ValueError(f"count must be at least 1; got {count}")
    known = sessions()
    stamp = _stamp(day)
    position = known.searchsorted(stamp, side="left") - count
    if position < 0:
        raise ValueError(
            f"only {known.searchsorted(stamp, side='left')} session(s) precede "
            f"{stamp.date()}; cannot go back {count}"
        )
    return known[position].date()


def horizon_end(day, count: int) -> date:
    """The `count`-th session after `day`, clamped to the last session on record.

    Clamping is deliberate: a horizon that runs past the end of the data is a
    normal condition near the present, and the caller reports it as an
    incomplete measurement rather than an error.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1; got {count}")
    known = sessions()
    stamp = _stamp(day)
    position = min(known.searchsorted(stamp, side="right") + count - 1, len(known) - 1)
    if position < 0:
        raise ValueError(_out_of_range(stamp))
    return known[position].date()


def between(start, end) -> list[date]:
    """Every session in the inclusive interval [start, end]."""
    known = sessions()
    left = known.searchsorted(_stamp(start), side="left")
    right = known.searchsorted(_stamp(end), side="right")
    return [stamp.date() for stamp in known[left:right]]


def session_count(start, end) -> int:
    """How many sessions fall in the inclusive interval [start, end]."""
    known = sessions()
    return int(
        known.searchsorted(_stamp(end), side="right")
        - known.searchsorted(_stamp(start), side="left")
    )


def schedule(start, end, freq: str = "QS", direction: str = "forward") -> list[date]:
    """Signal days on a pandas frequency, each snapped onto a real session.

    `pd.date_range(freq="QS")` yields quarter starts, most of which the market
    is closed for. Snapping keeps the intended cadence while ensuring every
    signal day is a date the market actually traded.

    `direction` decides which way a closed boundary moves. "forward" (the
    default) takes the period's opening session, which is what a period-start
    frequency such as "QS" or "MS" means; "backward" takes the last session of
    the preceding period, which is the right reading for as-of style cadences.
    Boundaries with no session on the chosen side are dropped rather than
    silently pulled to the other end of the data. Duplicates are dropped too, so
    a frequency finer than the session grid cannot emit one session twice.
    """
    if direction not in ("forward", "backward"):
        raise ValueError(
            f"direction must be 'forward' or 'backward'; got {direction!r}"
        )

    snap = align_forward if direction == "forward" else align
    aligned: list[date] = []
    for stamp in pd.date_range(_stamp(start), _stamp(end), freq=freq):
        try:
            session = snap(stamp)
        except ValueError:
            continue
        if not aligned or session != aligned[-1]:
            aligned.append(session)
    return aligned


if __name__ == "__main__":
    known = sessions()
    print(f"{len(known):,} sessions, {first_session()} -> {last_session()}")
    print(f"latest_session() = {latest_session()}")

    print("\nQUARTERLY SIGNAL DAYS, raw vs aligned")
    raw = pd.date_range("2016-01-01", "2025-01-01", freq="QS")
    closed = [d.date() for d in raw if not is_session(d)]
    print(f"  {len(closed)} of {len(raw)} quarter starts are not sessions")
    for stamp in raw[:4]:
        if stamp < known[0]:
            print(f"  {stamp.date()} -> dropped, precedes the loaded calendar")
            continue
        marker = "" if is_session(stamp) else "  <- market closed"
        print(f"  {stamp.date()} -> {align(stamp)}{marker}")
    print(f"  schedule() yields {len(schedule('2016-01-01', '2025-01-01'))} sessions")

    print("\n252-SESSION HORIZON, exact vs the 1.7x approximation")
    for day in ("2018-06-15", "2020-03-02", "2024-01-02"):
        exact = horizon_end(day, 252)
        span = (pd.Timestamp(exact) - pd.Timestamp(day)).days
        print(f"  {day} -> {exact}  ({span} calendar days, approximation used 443)")
