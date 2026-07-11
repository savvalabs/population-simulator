"""Engine core: process lifecycle, configuration, and the simulation calendar/time.

This subpackage holds the deterministic backbone every other subsystem sits on:

* :class:`EngineConfig` -- immutable, seeded engine-level configuration.
* :class:`Clock` / :class:`TimePoint` / :class:`SeasonCalendar` -- the simulation
  calendar and time model derived from a monotonic tick counter.
* :class:`Engine` / :class:`LifecycleState` -- the headless lifecycle driver that
  owns the configuration, the clock, and the run/pause/stop state machine.
"""

from __future__ import annotations

from .config import EngineConfig
from .engine import Engine, LifecycleState
from .time import Clock, SeasonCalendar, TimePoint

__all__ = [
    "EngineConfig",
    "Engine",
    "LifecycleState",
    "Clock",
    "SeasonCalendar",
    "TimePoint",
]
