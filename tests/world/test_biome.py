"""Tests for :mod:`population_engine.world.biome`."""

from __future__ import annotations

import pytest

from population_engine.world.biome import Biome


# -- matches ---------------------------------------------------------------


def test_biome_defaults_accept_everything() -> None:
    b = Biome("universal")
    assert b.matches(0, 0, 0)
    assert b.matches(5000, 40, 0.999)
    assert not b.matches(5000, 40, 1.0)  # humidity 1.0 is NOT < 1.0 (exclusive upper bound)


def test_biome_matches_narrow_range() -> None:
    b = Biome(
        "paramo",
        min_altitude=2800,
        max_altitude=4500,
        min_temperature=2,
        max_temperature=12,
        min_humidity=0.6,
        max_humidity=1.0,
    )
    assert b.matches(3000, 8, 0.8)
    assert not b.matches(2000, 8, 0.8)   # altitude too low
    assert not b.matches(3000, 15, 0.8)  # temperature too high
    assert not b.matches(3000, 8, 0.5)   # humidity too low
    assert not b.matches(3000, 8, 1.0)   # humidity at max (exclusive)


def test_biome_boundaries_inclusive_min_exclusive_max() -> None:
    b = Biome("test", min_altitude=100, max_altitude=200)
    assert b.matches(100, 0, 0)      # min inclusive
    assert not b.matches(200, 0, 0)  # max exclusive


# -- frozen / equality ----------------------------------------------------


def test_biome_is_frozen() -> None:
    b = Biome("tundra")
    with pytest.raises(Exception):
        b.name = "desert"  # type: ignore[misc]


def test_biome_equality() -> None:
    a = Biome("x", min_altitude=10, max_altitude=20)
    b = Biome("x", min_altitude=10, max_altitude=20)
    c = Biome("x", min_altitude=10, max_altitude=30)
    assert a == b
    assert a != c
    assert hash(a) == hash(b)
