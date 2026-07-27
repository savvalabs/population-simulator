"""Engine lifecycle and simulation-tick orchestration.

The :class:`Engine` is the single entry point a client uses to run the headless
simulation. It owns the configuration, the simulation clock, the seeded RNG, and
the lifecycle state machine, and it is the **sole orchestrator of the
simulation cycle**: the World, Scheduler, and EventBus are composed and called
only from :meth:`Engine._advance_one` and are mutually ignorant of one another.

The tick is composed in defined phases — clock advance, world halo refresh,
scheduler execute, event flush, structural commit — each gated on the presence
of its dependency. A bare ``Engine()`` (no deps supplied) retains its
lifecycle-only behaviour; supplying the deps activates the phases. See
ADR-004 for the structural-commit boundary.
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

from ..ecs.scheduler import SystemContext  # core orchestrates ecs; ecs never imports core
from .config import EngineConfig
from .time import Clock

if TYPE_CHECKING:
    from ..ecs.events import EventBus
    from ..ecs.registry import Registry
    from ..ecs.scheduler import Scheduler
    from ..world.world import World

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
        registry: "Registry | None" = None,
        scheduler: "Scheduler | None" = None,
        events: "EventBus | None" = None,
        world: "World | None" = None,
        data=None,
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
        # -- engine integration deps (S0 seam) -------------------------------
        # Engine is the SOLE orchestrator of the simulation cycle: these are
        # composed and driven only from _advance_one. They are mutually
        # ignorant; none imports or references another. All default to None so
        # a bare Engine() keeps its lifecycle-only behaviour (phases 2-4 are
        # gated on these being set).
        self._registry: "Registry | None" = registry
        self._scheduler: "Scheduler | None" = scheduler
        self._events: "EventBus | None" = events
        self._world: "World | None" = world
        # DataRegistry lands in S1; opaque to the engine until then.
        self._data = data
        # ADR-004 structural-commit boundary: structural requests (spawn /
        # despawn / add- / remove-component) queue here and are applied in
        # _structural_commit (after flush). Vacuous in S0; mechanics in S3.
        self._structural_requests: deque = deque()

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

        Composes the engine tick in defined phases. The engine is the sole
        orchestrator: World, Scheduler and EventBus are driven here and never
        reference one another. Each phase after the clock advance is gated on
        the presence of its dependency, so a bare ``Engine()`` (no deps
        supplied) advances only the clock — fully backward-compatible with the
        lifecycle-only engine.

        Phase 1 ``clock.advance`` — always.
        Phase 2 ``world.refresh_halos`` — if a world is attached.
        Phase 3 ``scheduler.execute(ctx)`` — if a scheduler is attached.
        Phase 4 ``events.flush`` — if an event bus is attached.
        Phase 5 ``_structural_commit`` — ADR-004 boundary; vacuous in S0.
        (Phase 6 — observer/client emit — lands with Census in S3.10.)
        """
        if self.config.max_ticks is not None and self.ticks_executed >= self.config.max_ticks:
            self.state = LifecycleState.STOPPED
            return False
        # Phase 1 — clock.
        self.clock.advance(1)
        self.ticks_executed += 1
        # Phase 2 — world halo refresh.
        if self._world is not None:
            self._world.refresh_halos()
        # Phase 3 — systems.
        if self._scheduler is not None:
            ctx = SystemContext(
                registry=self._registry,
                events=self._events,
                clock=self.clock,
                rng=self._rng,
                world=self._world,
                data=self._data,
            )
            self._scheduler.execute(ctx)
        # Phase 4 — event dispatch.
        if self._events is not None:
            self._events.flush()
        # Phase 5 — structural commit (ADR-004); vacuous in S0, filled in S3.
        self._structural_commit()
        return True

    def _structural_commit(self) -> None:
        """Apply queued structural changes after event dispatch (ADR-004).

        ADR-004 establishes that structural requests (spawn / despawn /
        add-component / remove-component) are NOT performed inline during
        ``Scheduler.execute``; they are queued and applied here, in a single
        commit phase run after ``EventBus.flush`` and before the next tick
        (despawns-then-spawns). This preserves the scheduler's invariant that
        archetypes do not mutate mid-``execute``, keeping parallel stages safe.

        S0 defines only the phase boundary: the request queue is empty (no
        system issues requests yet), so this is a no-op. The enqueue surface,
        despawn/spawn ordering and row-mutation mechanics arrive in S3 and will
        not amend this boundary. The V1 one-tick lag is current behaviour, not
        a permanent guarantee (per ADR-004).
        """
        # S0: the queue is empty — no system enqueues structural requests yet.
        # S3 drains self._structural_requests here (despawns then spawns).
        return
