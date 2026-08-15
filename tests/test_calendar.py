import pandas as pd
import pytest

import research.calendar as calendar

# A fortnight with the gaps that matter: New Year's Day is a holiday, and both
# weekends are closed. 2024-01-06/07 and 2024-01-13/14 never traded.
_SESSIONS = [
    "2024-01-02",
    "2024-01-03",
    "2024-01-04",
    "2024-01-05",
    "2024-01-08",
    "2024-01-09",
    "2024-01-10",
    "2024-01-11",
    "2024-01-12",
    "2024-01-15",
]


@pytest.fixture(autouse=True)
def loaded_calendar(monkeypatch):
    """Serve a known session list without touching the database, and make sure
    a test that forgets to patch cannot silently fall through to Postgres."""
    monkeypatch.setattr(
        calendar, "_sessions", pd.DatetimeIndex(pd.to_datetime(_SESSIONS))
    )
    monkeypatch.setattr(
        calendar,
        "get_connection",
        lambda: pytest.fail("calendar hit the database instead of its cache"),
    )


def test_is_session_distinguishes_open_days_from_closed_ones():
    assert calendar.is_session("2024-01-05")
    assert not calendar.is_session("2024-01-06")  # Saturday
    assert not calendar.is_session("2024-01-01")  # New Year's Day


def test_align_snaps_a_closed_day_back_to_the_prior_session():
    assert calendar.align("2024-01-07") == pd.Timestamp("2024-01-05").date()
    assert calendar.align("2024-01-13") == pd.Timestamp("2024-01-12").date()


def test_align_is_identity_on_a_session():
    assert calendar.align("2024-01-08") == pd.Timestamp("2024-01-08").date()


def test_align_clamps_a_future_day_to_the_last_loaded_session():
    assert calendar.align("2030-06-01") == pd.Timestamp("2024-01-15").date()


def test_align_rejects_a_day_before_the_calendar_starts():
    with pytest.raises(ValueError, match="outside the loaded calendar"):
        calendar.align("2023-12-29")


def test_latest_session_aligns_the_requested_as_of():
    assert calendar.latest_session("2024-01-06") == pd.Timestamp("2024-01-05").date()


def test_next_session_counts_forward_and_skips_the_weekend():
    assert calendar.next_session("2024-01-05") == pd.Timestamp("2024-01-08").date()
    assert calendar.next_session("2024-01-05", 3) == pd.Timestamp("2024-01-10").date()


def test_next_session_from_a_closed_day_starts_at_the_following_session():
    assert calendar.next_session("2024-01-06") == pd.Timestamp("2024-01-08").date()


def test_next_session_raises_when_the_data_runs_out():
    with pytest.raises(ValueError, match="cannot advance"):
        calendar.next_session("2024-01-12", 5)


def test_previous_session_counts_backward_and_skips_the_weekend():
    assert calendar.previous_session("2024-01-08") == pd.Timestamp("2024-01-05").date()
    assert (
        calendar.previous_session("2024-01-08", 3) == pd.Timestamp("2024-01-03").date()
    )


def test_previous_session_raises_when_the_data_runs_out():
    with pytest.raises(ValueError, match="cannot go back"):
        calendar.previous_session("2024-01-03", 5)


def test_horizon_end_lands_on_the_nth_session_after_the_signal_day():
    assert calendar.horizon_end("2024-01-05", 3) == pd.Timestamp("2024-01-10").date()


def test_horizon_end_clamps_instead_of_raising_when_the_horizon_overruns():
    """The distinguishing behaviour against next_session: a horizon running past
    the end of the data is normal near the present, and the caller reports it as
    an incomplete measurement."""
    assert calendar.horizon_end("2024-01-12", 500) == pd.Timestamp("2024-01-15").date()


def test_between_is_inclusive_of_both_endpoints():
    span = calendar.between("2024-01-04", "2024-01-09")
    assert span == [
        pd.Timestamp(day).date()
        for day in ("2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09")
    ]


def test_between_over_a_closed_interval_is_empty():
    assert calendar.between("2024-01-06", "2024-01-07") == []


def test_session_count_matches_the_listed_sessions():
    assert calendar.session_count("2024-01-04", "2024-01-09") == 4
    assert calendar.session_count("2024-01-06", "2024-01-07") == 0


def test_schedule_aligns_every_signal_day_onto_a_real_session():
    """The bug this module exists for: pd.date_range emits calendar dates the
    market was closed on, and they were being used as signal days verbatim."""
    days = calendar.schedule("2024-01-01", "2024-01-15", freq="W-SUN")
    assert days  # Sundays, every one of them a closed day
    assert all(calendar.is_session(day) for day in days)


def test_schedule_takes_the_opening_session_of_each_period():
    """A period-start frequency means the period's first session. Aligning
    backward would answer 2023-12-29 for January — the previous period."""
    days = calendar.schedule("2023-12-01", "2024-01-05", freq="MS")
    assert days == [pd.Timestamp("2024-01-02").date()]


def test_schedule_backward_reads_a_boundary_as_the_prior_period_close():
    days = calendar.schedule("2024-01-08", "2024-01-15", freq="W-MON")
    assert days == [
        pd.Timestamp("2024-01-08").date(),
        pd.Timestamp("2024-01-15").date(),
    ]
    backward = calendar.schedule("2024-01-13", "2024-01-15", freq="W-SAT")
    assert backward == [pd.Timestamp("2024-01-15").date()]


def test_schedule_collapses_boundaries_preceding_the_calendar_onto_its_start():
    """Forward alignment has somewhere to go for a pre-data boundary — the first
    loaded session — and deduplication keeps the run from repeating it."""
    assert calendar.schedule("2020-01-01", "2020-06-01", freq="MS") == [
        pd.Timestamp("2024-01-02").date()
    ]


def test_schedule_drops_boundaries_past_the_end_of_the_calendar():
    assert calendar.schedule("2030-01-01", "2030-06-01", freq="MS") == []


def test_schedule_never_repeats_a_session():
    days = calendar.schedule("2024-01-05", "2024-01-08", freq="D")
    assert len(days) == len(set(days))
