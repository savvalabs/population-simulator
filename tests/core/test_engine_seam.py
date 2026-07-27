"""S0 gate: the engine integration seam — six-phase tick composition and
reproducibility with a no-op system.

These tests exercise the S0 *seam*, not simulation behaviour. A no-op system
records the clock tick, draws one value from the shared rng, publishes one
event, and asserts the data slot is None and the world is attached — proving
every phase of the engine tick runs, in order, reproducibly. The existing
lifecycle suite (``tests/core/test_engine.py``) and scheduler suite stay green
unmodified; this file only adds coverage for the new composition.
"""

from __future__ import annotations

import numpy as np

from population_engine.core import Engine, EngineConfig
from population_engine.ecs.events import Event, EventBus
from population_engine.ecs.registry import Registry
from population_engine.ecs.scheduler import Scheduler, System, SystemContext
from population_engine.world.world import World


class TickPing(Event):
    """Published once per tick by the no-op system."""


class NoOpSystem(System):
    """Records each phase contribution; declares no component access."""

    name = "noop"
    reads: tuple = ()
    writes: tuple = ()

    def __init__(self) -> None:
        self.ticks: list[int] = []
        self.draws: list[int] = []
        self.data_seen: list[bool] = []
        self.world_seen: list[bool] = []

    def update(self, ctx: SystemContext) -> None:
        # Phase 1 already ran: the clock has advanced to this tick.
        self.ticks.append(ctx.clock.tick)
        # The engine's shared rng reaches systems reproducibly.
        self.draws.append(int(ctx.rng.integers(0, 1_000_000)))
        # S0: the data slot exists on the contract but S1 populates it.
        self.data_seen.append(ctx.data is None)
        # The world is passed through the seam (S1+ systems read it via ctx).
        self.world_seen.append(ctx.world is not None)
        # Phase 4 flush runs after phase 3; publish one event per tick.
        ctx.events.publish(TickPing())


def _engine(seed: int = 42, *, events: EventBus | None = None):
    """Build an Engine wired with the S0 deps + a fresh no-op system."""
    bus = events if events is not None else EventBus()
    scheduler = Scheduler()
    system = NoOpSystem()
    scheduler.add_system(system)
    world = World(seed=seed, width_chunks=1, height_chunks=1, chunk_size=8, halo=1)
    engine = Engine(
        EngineConfig(seed=seed),
        registry=Registry(),
        scheduler=scheduler,
        events=bus,
        world=world,
    )
    return engine, system


# --- bare engine unaffected by the seam ------------------------------------


def test_seam_bare_engine_unchanged() -> None:
    """A bare Engine() (no deps) still advances only clock + ticks."""
    e = Engine(EngineConfig(seed=42))
    assert e.run(3) == 3
    assert e.ticks_executed == 3
    assert e.clock.tick == 3
    # rng untouched by the (absent) system phase
    a = Engine(EngineConfig(seed=42))
    a.run(3)
    b = Engine(EngineConfig(seed=42))
    assert np.array_equal(
        a.rng.integers(0, 1_000_000, size=8),
        b.rng.integers(0, 1_000_000, size=8),
    )


# --- phase presence & order -------------------------------------------------


def test_seam_noop_system_runs_each_tick() -> None:
    e, sys_ = _engine()
    e.run(3)
    assert sys_.ticks == [1, 2, 3]
    assert len(sys_.draws) == 3


def test_seam_phase_order_clock_advances_before_system() -> None:
    """The clock has advanced to N by the time the system runs in tick N."""
    e, sys_ = _engine()
    e.run(5)
    assert sys_.ticks == [1, 2, 3, 4, 5]


# --- reproducibility --------------------------------------------------------


def test_seam_rng_reproducible_across_engines() -> None:
    e1, s1 = _engine(seed=42)
    e2, s2 = _engine(seed=42)
    e1.run(4)
    e2.run(4)
    assert s1.draws == s2.draws


# --- phase 4: events flushed each tick -------------------------------------


def test_seam_events_flushed_each_tick() -> None:
    events = EventBus()
    seen: list[int] = []
    events.subscribe(TickPing, lambda ev: seen.append(1))
    e, sys_ = _engine(events=events)
    e.run(3)
    assert len(seen) == 3
    assert events.pending() == 0
    assert sys_.ticks == [1, 2, 3]


# --- phase 2: world halos refreshed each tick ------------------------------


def test_seam_world_halos_refreshed_each_tick() -> None:
    world = World(seed=42, width_chunks=1, height_chunks=1, chunk_size=8, halo=1)
    # Construct the world BEFORE patching so its __init__ halo call is not
    # counted; World uses __slots__ (no instance attribute assignment), so
    # patch at the class level and restore in a finally.
    calls = {"n": 0}
    original = World.refresh_halos

    def spy(self_):
        calls["n"] += 1
        return original(self_)

    World.refresh_halos = spy  # type: ignore[method-assign]
    try:
        scheduler = Scheduler()
        scheduler.add_system(NoOpSystem())
        e = Engine(
            EngineConfig(seed=42),
            registry=Registry(),
            scheduler=scheduler,
            events=EventBus(),
            world=world,
        )
        e.run(3)
    finally:
        World.refresh_halos = original
    assert calls["n"] == 3


# --- seam fields populated --------------------------------------------------


def test_seam_world_passed_on_context() -> None:
    e, sys_ = _engine()
    e.run(1)
    assert sys_.world_seen == [True]


def test_seam_data_slot_none_until_s1() -> None:
    e, sys_ = _engine()
    e.run(2)
    assert sys_.data_seen == [True, True]
