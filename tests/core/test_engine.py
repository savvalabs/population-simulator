"""Tests for :mod:`population_engine.core.engine`."""

from __future__ import annotations

import numpy as np
import pytest

from population_engine.core import Clock, Engine, EngineConfig, LifecycleState


# --- construction ----------------------------------------------------------

def test_defaults() -> None:
    e = Engine()
    assert e.state is LifecycleState.CREATED
    assert e.speed == 1.0
    assert e.ticks_executed == 0
    assert e.clock.ticks_per_day == e.config.ticks_per_day
    assert isinstance(e.rng, np.random.Generator)


def test_clock_config_mismatch_raises() -> None:
    bad_clock = Clock(ticks_per_day=99)
    with pytest.raises(ValueError, match="ticks_per_day"):
        Engine(EngineConfig(ticks_per_day=24), clock=bad_clock)


def test_explicit_clock_accepted_when_consistent() -> None:
    clock = Clock(ticks_per_day=12)
    e = Engine(EngineConfig(ticks_per_day=12), clock=clock)
    assert e.clock is clock


def test_rng_determinism_through_engine() -> None:
    a = Engine(EngineConfig(seed=42))
    b = Engine(EngineConfig(seed=42))
    assert np.array_equal(
        a.rng.integers(0, 1_000_000, size=8),
        b.rng.integers(0, 1_000_000, size=8),
    )


# --- start / pause / resume / stop -----------------------------------------

def test_start_from_created() -> None:
    e = Engine()
    e.start()
    assert e.state is LifecycleState.RUNNING
    # idempotent
    e.start()
    assert e.state is LifecycleState.RUNNING


def test_start_from_stopped_raises() -> None:
    e = Engine()
    e.start()
    e.stop()
    with pytest.raises(RuntimeError, match="stopped"):
        e.start()


def test_pause_requires_running() -> None:
    e = Engine()
    with pytest.raises(RuntimeError, match="pause"):
        e.pause()
    e.start()
    e.pause()
    assert e.state is LifecycleState.PAUSED
    with pytest.raises(RuntimeError, match="pause"):
        e.pause()


def test_resume_requires_paused() -> None:
    e = Engine()
    with pytest.raises(RuntimeError, match="resume"):
        e.resume()
    e.start()
    with pytest.raises(RuntimeError, match="resume"):
        e.resume()
    e.pause()
    e.resume()
    assert e.state is LifecycleState.RUNNING


def test_stop_is_idempotent_from_any_state() -> None:
    e = Engine()
    e.stop()
    assert e.state is LifecycleState.STOPPED
    e.stop()  # again, no-op
    assert e.state is LifecycleState.STOPPED


# --- ticking ---------------------------------------------------------------

def test_tick_requires_running() -> None:
    e = Engine()
    with pytest.raises(RuntimeError, match="cannot tick"):
        e.tick()
    e.start()
    e.tick()
    assert e.ticks_executed == 1
    assert e.clock.tick == 1


def test_tick_blocked_when_paused() -> None:
    e = Engine()
    e.start()
    e.pause()
    with pytest.raises(RuntimeError, match="cannot tick"):
        e.tick()


def test_run_autostarts_from_created() -> None:
    e = Engine()
    n = e.run(7)
    assert n == 7
    assert e.state is LifecycleState.RUNNING
    assert e.ticks_executed == 7
    assert e.clock.tick == 7


def test_run_after_explicit_start() -> None:
    e = Engine()
    e.start()
    assert e.run(3) == 3
    assert e.clock.tick == 3


def test_run_zero_does_not_advance() -> None:
    e = Engine()
    assert e.run(0) == 0
    assert e.ticks_executed == 0


def test_run_rejects_negative() -> None:
    e = Engine()
    with pytest.raises(ValueError, match="n_ticks"):
        e.run(-1)


def test_run_refuses_when_paused() -> None:
    e = Engine()
    e.start()
    e.pause()
    with pytest.raises(RuntimeError, match="cannot run"):
        e.run(5)


def test_pause_resume_breaks_progress() -> None:
    e = Engine()
    e.run(4)
    e.pause()
    # no progress while paused
    before = e.ticks_executed
    e.resume()
    e.run(2)
    assert e.ticks_executed == before + 2


def test_tick_after_stop_raises() -> None:
    e = Engine()
    e.run(5)
    e.stop()
    with pytest.raises(RuntimeError, match="cannot tick"):
        e.tick()


# --- max_ticks budget ------------------------------------------------------

def test_run_stops_at_max_ticks_budget() -> None:
    e = Engine(EngineConfig(max_ticks=3))
    executed = e.run(5)
    assert executed == 3
    assert e.ticks_executed == 3
    assert e.state is LifecycleState.STOPPED
    assert e.clock.tick == 3


def test_run_exactly_budget_leaves_running() -> None:
    e = Engine(EngineConfig(max_ticks=3))
    assert e.run(3) == 3
    # budget met but not exceeded -> still runnable
    assert e.state is LifecycleState.RUNNING
    # next run immediately exhausts
    assert e.run(5) == 0
    assert e.state is LifecycleState.STOPPED


def test_tick_exhausts_budget_without_advancing() -> None:
    e = Engine(EngineConfig(max_ticks=2))
    e.run(2)  # meets budget, state still RUNNING
    e.tick()  # attempts 3rd -> exhausts, no advance
    assert e.ticks_executed == 2
    assert e.clock.tick == 2
    assert e.state is LifecycleState.STOPPED
    with pytest.raises(RuntimeError, match="cannot tick"):
        e.tick()


# --- speed -----------------------------------------------------------------

def test_set_speed_clamps_to_envelope() -> None:
    e = Engine(EngineConfig(min_speed=0.0, max_speed=10.0))
    e.set_speed(5.5)
    assert e.speed == 5.5
    with pytest.raises(ValueError, match="speed"):
        e.set_speed(-0.1)
    with pytest.raises(ValueError, match="speed"):
        e.set_speed(10.1)
