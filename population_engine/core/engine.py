"""Engine lifecycle.

The :class:`Engine` owns the engine configuration, the simulation clock, and the
lifecycle state machine that drives it. It is the single entry point a client
uses to run the headless simulation.

``core`` deliberately stops at lifecycle + time. The world, entities, systems,
and the scheduler (see the ``ecs`` and ``world`` subsystems) plug into the engine
*after* those subsystems land; the engine exposes its :attr:`clock` and
:attr:`rng` so later work can compose without rewriting this module.
"""

from __future__ import annotations

from enum import Enum

import numpy as np

from .config import EngineConfig
from .time import Clock

__all__ = ["LifecycleState", "Engine"]


class LifecycleState(Enum):
    """Finite lifecycle states of an :class:`Engine`."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class Engine:
    """Headless simulation lifecycle driver.

    A thin, real backbone: it owns a seeded random generator (so the simulation
    is reproducible) and the simulation :class:`Clock`, and it enforces the
    CREATED -> RUNNING <-> PAUSED -> STOPPED transition graph. Each
    :meth:`tick` advances the clock by one tick; :meth:`run` loops synchronously
    for a bounded number of ticks.

    The clock's ``ticks_per_day`` must match the configuration's; passing an
    inconsistent clock is a programming error.
    """

    def __init__(
        self,
        config: EngineConfig | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.config = config if config is not None else EngineConfig()
        self.clock = (
            clock
            if clock is not None
            else Clock(ticks_per_day=self.config.ticks_per_day)
        )
        if self.clock.ticks_per_day != self.config.ticks_per_day:
            raise ValueError(
                "clock.ticks_per_day "
                f"({self.clock.ticks_per_day}) must match "
                f"config.ticks_per_day ({self.config.ticks_per_day})"
            )
        # Hold a single generator instance so tick-by-tick consumption by later
        # systems is reproducible across runs with the same seed.
        self._rng: np.random.Generator = self.config.rng()
        self.state: LifecycleState = LifecycleState.CREATED
        self.speed: float = self.config.default_speed
        self.ticks_executed: int = 0

    @property
    def rng(self) -> np.random.Generator:
        """The engine's deterministic random generator (shared across systems)."""
        return self._rng

    # -- lifecycle control -------------------------------------------------

    def start(self) -> None:
        """Transition CREATED -> RUNNING. Idempotent if already running."""
        if self.state == LifecycleState.RUNNING:
            return
        if self.state == LifecycleState.STOPPED:
            raise RuntimeError("engine is stopped; construct a new Engine to run again")
        self.state = LifecycleState.RUNNING

    def pause(self) -> None:
        """Transition RUNNING -> PAUSED."""
        if self.state != LifecycleState.RUNNING:
            raise RuntimeError(f"can only pause a running engine (state={self.state.value})")
        self.state = LifecycleState.PAUSED

    def resume(self) -> None:
        """Transition PAUSED -> RUNNING."""
        if self.state != LifecycleState.PAUSED:
            raise RuntimeError(f"can only resume a paused engine (state={self.state.value})")
        self.state = LifecycleState.RUNNING

    def stop(self) -> None:
        """Transition any state -> STOPPED. Idempotent."""
        self.state = LifecycleState.STOPPED

    def set_speed(self, speed: float) -> None:
        """Clamp ``speed`` into the configured envelope and store it.

        ``speed`` is a control hint for a real-time driver; it does not affect
        synchronous :meth:`tick` / :meth:`run`.
        """
        speed = float(speed)
        if not (self.config.min_speed <= speed <= self.config.max_speed):
            raise ValueError(
                f"speed {speed} outside [{self.config.min_speed}, {self.config.max_speed}]"
            )
        self.speed = speed

    # -- ticking -----------------------------------------------------------

    def tick(self) -> None:
        """Advance the simulation by exactly one tick.

        Raises if the engine is not running. If the tick budget
        (``config.max_ticks``) is exhausted, the engine auto-stops instead of
        advancing.
        """
        if self.state != LifecycleState.RUNNING:
            raise RuntimeError(f"cannot tick: engine is {self.state.value}")
        self._advance_one()

    def run(self, n_ticks: int) -> int:
        """Run up to ``n_ticks`` synchronous ticks.

        Auto-starts from CREATED for convenience. Returns the number of ticks
        actually executed (may be fewer if stopped, paused, or the tick budget
        is exhausted).
        """
        if not isinstance(n_ticks, int) or isinstance(n_ticks, bool):
            raise TypeError(f"n_ticks must be an int, got {type(n_ticks).__name__}")
        if n_ticks < 0:
            raise ValueError(f"n_ticks must be >= 0, got {n_ticks!r}")

        if self.state == LifecycleState.CREATED:
            self.start()
        if self.state != LifecycleState.RUNNING:
            raise RuntimeError(
                f"cannot run: engine is {self.state.value}; start or resume it"
            )

        executed = 0
        while executed < n_ticks and self.state == LifecycleState.RUNNING:
            if not self._advance_one():
                # Tick budget exhausted -> engine auto-stopped.
                break
            executed += 1
        return executed

    def _advance_one(self) -> bool:
        """Advance one tick if the budget allows.

        Returns ``True`` if a tick was executed, ``False`` (and auto-stops the
        engine) when ``config.max_ticks`` is reached.
        """
        if self.config.max_ticks is not None and self.ticks_executed >= self.config.max_ticks:
            self.state = LifecycleState.STOPPED
            return False
        self.clock.advance(1)
        self.ticks_executed += 1
        return True
