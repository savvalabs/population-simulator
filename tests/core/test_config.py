"""Tests for :mod:`population_engine.core.config`."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from population_engine.core import EngineConfig


def test_defaults_are_sane() -> None:
    cfg = EngineConfig()
    assert cfg.seed == 0
    assert cfg.ticks_per_day == 24
    assert cfg.start_tick == 0
    assert cfg.max_ticks is None
    assert cfg.default_speed == 1.0
    assert cfg.min_speed == 0.0
    assert cfg.max_speed == 100.0


def test_is_frozen() -> None:
    cfg = EngineConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.seed = 5  # type: ignore[misc]


@pytest.mark.parametrize("bad", [0, -1])
def test_ticks_per_day_must_be_positive(bad: int) -> None:
    with pytest.raises(ValueError, match="ticks_per_day"):
        EngineConfig(ticks_per_day=bad)


def test_start_tick_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="start_tick"):
        EngineConfig(start_tick=-1)


def test_max_ticks_must_be_non_negative_or_none() -> None:
    with pytest.raises(ValueError, match="max_ticks"):
        EngineConfig(max_ticks=-1)
    # None is accepted
    assert EngineConfig(max_ticks=None).max_ticks is None


def test_speed_envelope_validation() -> None:
    with pytest.raises(ValueError, match="min_speed"):
        EngineConfig(min_speed=-1.0)
    with pytest.raises(ValueError, match="min_speed"):
        EngineConfig(min_speed=5.0, max_speed=1.0)
    with pytest.raises(ValueError, match="default_speed"):
        EngineConfig(default_speed=0.5, min_speed=1.0)
    with pytest.raises(ValueError, match="default_speed"):
        EngineConfig(default_speed=200.0)
    # valid envelope inside the bounds
    cfg = EngineConfig(min_speed=0.5, default_speed=1.5, max_speed=4.0)
    assert cfg.default_speed == 1.5


def test_rng_is_a_generator() -> None:
    assert isinstance(EngineConfig().rng(), np.random.Generator)


def test_rng_is_deterministic_for_same_seed() -> None:
    a = EngineConfig(seed=7).rng()
    b = EngineConfig(seed=7).rng()
    assert np.array_equal(a.integers(0, 1_000_000, size=10), b.integers(0, 1_000_000, size=10))


def test_rng_differs_for_different_seeds() -> None:
    a = EngineConfig(seed=7).rng()
    b = EngineConfig(seed=8).rng()
    assert not np.array_equal(a.integers(0, 1_000_000, size=10), b.integers(0, 1_000_000, size=10))
