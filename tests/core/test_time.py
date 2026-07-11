"""Tests for :mod:`population_engine.core.time`."""

from __future__ import annotations

import dataclasses
import datetime as _dt

import pytest

from population_engine.core.time import (
    DEFAULT_START_DATE,
    DEFAULT_TICKS_PER_DAY,
    Clock,
    SeasonCalendar,
    TimePoint,
)

DAYS_IN = {
    1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}


def test_defaults() -> None:
    assert DEFAULT_TICKS_PER_DAY == 24
    assert DEFAULT_START_DATE == _dt.date(2000, 1, 1)
    c = Clock()
    assert c.ticks_per_day == 24
    assert c.start_date == DEFAULT_START_DATE
    assert c.tick == 0


# --- SeasonCalendar --------------------------------------------------------

def test_tropical_default_covers_all_months() -> None:
    cal = SeasonCalendar.tropical_dry_rainy()
    for month in range(1, 13):
        assert cal.season_of(month) in ("dry", "rainy")
    assert cal.season_of(1) == "dry"
    assert cal.season_of(4) == "rainy"
    assert cal.season_of(12) == "dry"


def test_season_calendar_requires_all_twelve_months() -> None:
    partial = {m: "x" for m in range(1, 12)}  # missing month 12
    with pytest.raises(ValueError, match="missing"):
        SeasonCalendar(month_to_season=partial)


@pytest.mark.parametrize("month", [0, 13, -1])
def test_season_of_validates_month(month: int) -> None:
    with pytest.raises(ValueError, match="month"):
        SeasonCalendar.tropical_dry_rainy().season_of(month)


def test_custom_season_calendar() -> None:
    four = {1: "winter", 2: "winter", 12: "winter",
            3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer",
            9: "autumn", 10: "autumn", 11: "autumn"}
    cal = SeasonCalendar(month_to_season=four)
    assert cal.season_of(1) == "winter"
    assert cal.season_of(6) == "summer"


# --- Clock construction & advance -----------------------------------------

def test_clock_validates_ticks_per_day() -> None:
    with pytest.raises(ValueError, match="ticks_per_day"):
        Clock(ticks_per_day=0)


def test_clock_validates_tick_nonnegative() -> None:
    with pytest.raises(ValueError, match="tick"):
        Clock(tick=-1)


def test_advance_rejects_negative() -> None:
    c = Clock()
    with pytest.raises(ValueError, match="ticks"):
        c.advance(-1)


def test_advance_zero_is_noop() -> None:
    c = Clock()
    c.advance(0)
    assert c.tick == 0


# --- Clock.now() derivation ------------------------------------------------

def test_now_at_epoch() -> None:
    c = Clock()
    tp = c.now()
    assert tp.tick == 0
    assert tp.date == _dt.date(2000, 1, 1)
    assert tp.year == 2000 and tp.month == 1 and tp.day == 1
    assert tp.day_of_year == 1
    assert tp.ticks_into_day == 0
    assert tp.time_of_day_fraction == 0.0
    assert tp.season == "dry"


def test_now_within_first_day() -> None:
    c = Clock(ticks_per_day=24)
    c.advance(1)
    tp = c.now()
    assert tp.tick == 1
    assert tp.date == _dt.date(2000, 1, 1)
    assert tp.ticks_into_day == 1
    assert tp.time_of_day_fraction == pytest.approx(1 / 24)
    assert tp.ticks_into_day == c.tick % c.ticks_per_day


def test_full_day_rolls_over() -> None:
    c = Clock(ticks_per_day=24)
    c.advance(24)
    tp = c.now()
    assert tp.date == _dt.date(2000, 1, 2)
    assert tp.ticks_into_day == 0
    assert tp.time_of_day_fraction == 0.0


def test_leap_year_day_exists_on_2000() -> None:
    # 2000 is a leap year; Feb 29 should be reachable and correct.
    c = Clock(ticks_per_day=24, start_date=_dt.date(2000, 1, 1))
    c.advance(24 * (DAYS_IN[1] + 28))  # Jan 31 + Feb 28 = day 59 -> Feb 29
    tp = c.now()
    assert tp.date == _dt.date(2000, 2, 29)
    assert tp.month == 2 and tp.day == 29
    assert tp.day_of_year == 31 + 29


def test_non_leap_year_march_first() -> None:
    # 2001 is not a leap year; Feb has 28 days.
    c = Clock(ticks_per_day=24, start_date=_dt.date(2001, 1, 1))
    c.advance(24 * (DAYS_IN[1] + DAYS_IN[2]))  # -> Mar 1
    tp = c.now()
    assert tp.date == _dt.date(2001, 3, 1)
    assert tp.day_of_year == 31 + 28 + 1


def test_season_transitions_from_dry_to_rainy() -> None:
    # Jan 1 2000 -> Apr 1 2000 crosses from dry into rainy.
    c = Clock(ticks_per_day=24)
    c.advance(24 * (DAYS_IN[1] + 29 + DAYS_IN[3]))  # Jan(31)+Feb(29)+Mar(31) = 91 days
    tp = c.now()
    assert tp.date == _dt.date(2000, 4, 1)
    assert tp.season == "rainy"


def test_custom_calendar_reflected_in_now() -> None:
    four = {1: "winter", 2: "winter", 12: "winter",
            3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer",
            9: "autumn", 10: "autumn", 11: "autumn"}
    c = Clock(start_date=_dt.date(2000, 6, 15), season_calendar=SeasonCalendar(four))
    assert c.now().season == "summer"


def test_timepoint_is_frozen() -> None:
    tp = Clock().now()
    with pytest.raises(dataclasses.FrozenInstanceError):
        tp.season = "rainy"  # type: ignore[misc]


def test_clock_advances_monotonically_over_many_ticks() -> None:
    c = Clock(ticks_per_day=24)
    c.advance(24 * 366 + 10)  # leap-year 2000 (366 days) + 10 ticks -> 2001-01-01
    tp = c.now()
    assert tp.year == 2001
    assert tp.ticks_into_day == 10
