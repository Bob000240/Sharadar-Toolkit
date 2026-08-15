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
    """Return every session on record, ascending.

    Read once and cached for the life of the process. Raise RuntimeError when
    no price data has been loaded, since there is no calendar to derive.
    """
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
    """Drop the cached session list so the next call re-reads the database.

    Needed only by a long-running process that must see dates loaded after it
    started.
    """
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
    """Return the earliest session on record."""
    return sessions()[0].date()


def last_session() -> date:
    """Return the latest session on record.

    This is the newest date the data can support, which is not necessarily the
    latest session the market has held.
    """
    return sessions()[-1].date()


def is_session(day) -> bool:
    """Return True when the market produced prices on ``day``."""
    return _stamp(day) in sessions()


def align(day) -> date:
    """Return the latest session on or before ``day``.

    This is the honest as-of date for a request made on ``day``. A day past the
    end of the data aligns to the last session on record. Raise ValueError when
    ``day`` precedes the first session.
    """
    known = sessions()
    stamp = _stamp(day)
    position = known.searchsorted(stamp, side="right") - 1
    if position < 0:
        raise ValueError(_out_of_range(stamp))
    return known[position].date()


def align_forward(day) -> date:
    """Return the earliest session on or after ``day``.

    The opening session of a period that begins on ``day``, and the mirror of
    ``align``, which looks backward for an as-of date. Raise ValueError when the
    data does not reach ``day``.
    """
    known = sessions()
    stamp = _stamp(day)
    position = known.searchsorted(stamp, side="left")
    if position >= len(known):
        raise ValueError(_out_of_range(stamp))
    return known[position].date()


def latest_session(as_of=None) -> date:
    """Return the session a screen run at ``as_of`` should use.

    Defaults to today. An alias for ``align`` that reads better at call sites
    deciding when to run rather than what to align.
    """
    return align(date.today() if as_of is None else as_of)


def next_session(day, count: int = 1) -> date:
    """Return the ``count``-th session strictly after ``day``.

    Raise ValueError when ``count`` is below 1, or when the data does not extend
    that far. Use ``horizon_end`` instead where running off the end of the data
    is expected rather than exceptional.
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
    """Return the ``count``-th session strictly before ``day``.

    Raise ValueError when ``count`` is below 1, or when the data does not reach
    back that far.
    """
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
    """Return the ``count``-th session after ``day``, clamped to the last on record.

    Clamping is deliberate: a horizon that runs past the end of the data is a
    normal condition near the present, and the caller reports it as an
    incomplete measurement rather than an error. Raise ValueError only when
    ``count`` is below 1 or ``day`` precedes the calendar entirely.
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
    """Return every session in the inclusive interval [``start``, ``end``]."""
    known = sessions()
    left = known.searchsorted(_stamp(start), side="left")
    right = known.searchsorted(_stamp(end), side="right")
    return [stamp.date() for stamp in known[left:right]]


def session_count(start, end) -> int:
    """Return how many sessions fall in [``start``, ``end``], inclusive."""
    known = sessions()
    return int(
        known.searchsorted(_stamp(end), side="right")
        - known.searchsorted(_stamp(start), side="left")
    )


def schedule(start, end, freq: str = "QS", direction: str = "forward") -> list[date]:
    """Return signal days on a pandas frequency, each snapped onto a session.

    ``pd.date_range(freq="QS")`` yields quarter starts, most of which the market
    is closed for. Snapping keeps the intended cadence while ensuring every
    signal day is a date the market actually traded.

    ``direction`` decides which way a closed boundary moves. "forward", the
    default, takes the period's opening session, which is what a period-start
    frequency such as "QS" or "MS" means; "backward" takes the last session of
    the preceding period, which is the right reading for as-of style cadences.
    Boundaries with no session on the chosen side are dropped rather than
    silently pulled to the other end of the data, and duplicates are dropped
    too, so a frequency finer than the session grid cannot emit one session
    twice.

    Raise ValueError for a direction other than "forward" or "backward".
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
