"""Simulation time and calendar.

The simulated world keeps a single monotonic ``tick`` counter. The calendar
derives a concrete civil date (year / month / day), a time-of-day fraction, and a
season label from that counter. Because the only engine dependency for time is
the ``ticks_per_day`` scale (see :class:`~population_engine.core.config
.EngineConfig`), this module is self-contained and has no dependence on the
world, ECS, or any plugin.

Seasons are data-driven through a :class:`SeasonCalendar` that maps calendar
months (1-12) to labels. The bundled default approximates the two-season
tropical regime of the Sierra Nevada de Santa Marta (dry / rainy), but it is a
plain value object that can be substituted or extended without touching engine
code.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Mapping

__all__ = [
    "SeasonCalendar",
    "DEFAULT_TICKS_PER_DAY",
    "DEFAULT_START_DATE",
    "TimePoint",
    "Clock",
]

#: Default ticks-per-day when none is supplied explicitly.
DEFAULT_TICKS_PER_DAY: int = 24

#: Default simulation epoch (1 Jan, year 2000). The anchor is arbitrary; only
#: the relative day/month/year arithmetic is meaningful for the simulation.
DEFAULT_START_DATE: _dt.date = _dt.date(2000, 1, 1)


@dataclass(frozen=True)
class SeasonCalendar:
    """Mapping from calendar month (1-12) to a season label.

    A value object: build one with whatever month-to-season scheme the simulation
    needs and pass it to a :class:`Clock`. Labels are free-form strings (e.g.
    ``"dry"`` / ``"rainy"`` or ``"winter"`` / ``"summer"``).
    """

    month_to_season: Mapping[int, str]

    def __post_init__(self) -> None:
        missing = [m for m in range(1, 13) if m not in self.month_to_season]
        if missing:
            raise ValueError(
                f"SeasonCalendar must cover all 12 months; missing: {missing}"
            )

    @classmethod
    def tropical_dry_rainy(cls) -> "SeasonCalendar":
        """Default two-season tropical calendar for the Sierra Nevada context.

        Dry season runs December-March, rainy season April-November. This is a
        coarse approximation tuned for use as a sensible default; supply a
        custom :class:`SeasonCalendar` for finer resolution.
        """
        dry = {12, 1, 2, 3}
        rainy = {4, 5, 6, 7, 8, 9, 10, 11}
        labels: dict[int, str] = {m: "dry" for m in dry}
        labels.update({m: "rainy" for m in rainy})
        return cls(month_to_season=labels)

    def season_of(self, month: int) -> str:
        month = _validate_month(month)
        return self.month_to_season[month]


def _validate_month(month: int) -> int:
    if not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError(f"month must be an int in 1..12, got {month!r}")
    return month


@dataclass(frozen=True)
class TimePoint:
    """An immutable snapshot of the simulation clock at one instant."""

    #: Absolute tick index this point corresponds to.
    tick: int
    #: Civil date in the simulation calendar.
    date: _dt.date
    #: Day of the year (1-366), accounting for leap years.
    day_of_year: int
    #: Fraction of the current day elapsed, in ``[0.0, 1.0)``.
    time_of_day_fraction: float
    #: Number of ticks elapsed into the current day, in ``[0, ticks_per_day)``.
    ticks_into_day: int
    #: Season label for the current month.
    season: str
    #: Calendar year.
    year: int
    #: Calendar month (1-12).
    month: int
    #: Day of the month (1-31).
    day: int


@dataclass
class Clock:
    """The simulation timekeeper.

    Holds a monotonic ``tick`` counter and derives calendar fields from it
    relative to a fixed ``start_date`` anchor and a ``ticks_per_day`` scale.
    """

    ticks_per_day: int = DEFAULT_TICKS_PER_DAY
    start_date: _dt.date = DEFAULT_START_DATE
    season_calendar: SeasonCalendar = field(default_factory=SeasonCalendar.tropical_dry_rainy)
    #: Absolute simulation tick. Advanced by :meth:`advance`.
    tick: int = 0

    def __post_init__(self) -> None:
        if self.ticks_per_day < 1:
            raise ValueError(
                f"ticks_per_day must be >= 1, got {self.ticks_per_day!r}"
            )
        if not isinstance(self.start_date, _dt.date):
            raise TypeError(
                f"start_date must be a datetime.date, got {type(self.start_date).__name__}"
            )
        if self.tick < 0:
            raise ValueError(f"tick must be >= 0, got {self.tick!r}")

    def advance(self, ticks: int = 1) -> None:
        """Advance the clock by ``ticks`` (must be non-negative)."""
        if ticks < 0:
            raise ValueError(f"ticks must be >= 0, got {ticks!r}")
        self.tick += ticks

    def now(self) -> TimePoint:
        """Return an immutable snapshot of the clock at its current tick."""
        elapsed_days, ticks_into_day = divmod(self.tick, self.ticks_per_day)
        date = self.start_date + _dt.timedelta(days=elapsed_days)
        return TimePoint(
            tick=self.tick,
            date=date,
            day_of_year=date.timetuple().tm_yday,
            time_of_day_fraction=ticks_into_day / self.ticks_per_day,
            ticks_into_day=ticks_into_day,
            season=self.season_calendar.season_of(date.month),
            year=date.year,
            month=date.month,
            day=date.day,
        )
