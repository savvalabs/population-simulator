"""Tests for :mod:`population_engine.world.field`."""

from __future__ import annotations

import numpy as np
import pytest

from population_engine.world.field import (
    DEFAULT_HALO,
    FIELD_NAMES,
    FIELD_SCHEMA,
    Field,
)


# -- construction ----------------------------------------------------------


def test_field_shape_and_dtype() -> None:
    f = Field("altitude", np.float64, chunk_size=4, halo=1)
    assert f.name == "altitude"
    assert f.chunk_size == 4
    assert f.halo == 1
    assert f.dtype == np.dtype(np.float64)
    assert f.shape == (6, 6)
    assert f.interior.shape == (4, 4)


def test_field_default_fill() -> None:
    f = Field("temperature", np.float64, chunk_size=4, halo=1, default=25.0)
    assert np.all(f.interior == 25.0)
    # The whole padded buffer, including halo, starts at the default.
    assert f.data[0, 0] == 25.0
    assert f.data[5, 5] == 25.0


def test_field_prefilled_interior_copied() -> None:
    interior = np.arange(16, dtype=np.float64).reshape(4, 4)
    f = Field("altitude", np.float64, chunk_size=4, halo=1, interior=interior)
    assert np.array_equal(f.interior, interior)
    # Halo region stays at the default (0.0), not the interior.
    assert f.data[0, 0] == 0.0
    assert f.data[5, 5] == 0.0


def test_field_constructor_invalid_sizes_raise() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        Field("altitude", np.float64, chunk_size=0, halo=1)
    with pytest.raises(ValueError, match="halo"):
        Field("altitude", np.float64, chunk_size=4, halo=0)


def test_field_prefilled_wrong_shape_raises() -> None:
    bad = np.zeros((3, 4), dtype=np.float64)
    with pytest.raises(ValueError, match="shape"):
        Field("altitude", np.float64, chunk_size=4, halo=1, interior=bad)


def test_field_prefilled_wrong_dtype_raises() -> None:
    # biome_id field is int64; feeding float interior is a dtype mismatch.
    bad = np.zeros((4, 4), dtype=np.float64)
    with pytest.raises(ValueError, match="dtype"):
        Field("biome_id", np.int64, chunk_size=4, halo=1, interior=bad)


# -- read-only halo / writable interior ------------------------------------


def test_field_data_is_read_only() -> None:
    f = Field("altitude", np.float64, chunk_size=4, halo=1)
    assert f.data.flags.writeable is False
    with pytest.raises(ValueError):
        f.data[0, 0] = 1.0


def test_field_interior_is_writable_and_flows_to_data() -> None:
    f = Field("altitude", np.float64, chunk_size=4, halo=1)
    assert f.interior.flags.writeable is True
    f.interior[1, 2] = 9.0
    h = f.halo
    # Shared buffer: the write is visible through the read-only data view.
    assert f.data[h + 1, h + 2] == 9.0
    # data itself is still read-only.
    with pytest.raises(ValueError):
        f.data[0, 0] = 1.0


def test_field_interior_write_does_not_touch_halo() -> None:
    f = Field("altitude", np.float64, chunk_size=4, halo=1, default=0.0)
    f.interior[2, 3] = 7.0
    # Every halo cell is still the default 0.0.
    h = f.halo
    assert f.data[0, :] == pytest.approx(0.0)
    assert f.data[-1, :] == pytest.approx(0.0)
    assert f.data[:, 0] == pytest.approx(0.0)
    assert f.data[:, -1] == pytest.approx(0.0)


# -- fill_halo -------------------------------------------------------------


def test_field_fill_halo_copies_ring_only() -> None:
    interior = np.full((4, 4), 100.0, dtype=np.float64)
    f = Field("altitude", np.float64, chunk_size=4, halo=1, interior=interior)
    h = f.halo
    # Padded context: ring set to sentinel distances, interior echoes the field.
    padded = np.full((6, 6), 500.0, dtype=np.float64)
    padded[h : h + 4, h : h + 4] = interior  # so centers agree by construction
    f.fill_halo(padded)
    # Halo ring now matches padded; interior unchanged.
    assert f.data[0, 1] == 500.0
    assert f.data[5, 5] == 500.0
    assert np.array_equal(f.interior, interior)


def test_field_fill_halo_wrong_shape_raises() -> None:
    f = Field("altitude", np.float64, chunk_size=4, halo=1)
    with pytest.raises(ValueError, match="shape"):
        f.fill_halo(np.zeros((5, 6), dtype=np.float64))


def test_field_fill_halo_wrong_dtype_raises() -> None:
    f = Field("altitude", np.float64, chunk_size=4, halo=1)
    with pytest.raises(ValueError, match="dtype"):
        f.fill_halo(np.zeros((6, 6), dtype=np.int64))


# -- halo width > 1 --------------------------------------------------------


def test_field_halo_width_2() -> None:
    f = Field("altitude", np.float64, chunk_size=3, halo=2)
    assert f.shape == (7, 7)
    assert f.interior.shape == (3, 3)
    padded = np.arange(49, dtype=np.float64).reshape(7, 7)
    interior = f.interior.copy()
    f.fill_halo(padded)
    h = f.halo
    # Width-2 ring refreshed; interior untouched.
    assert f.data[0, 0] == 0.0
    assert f.data[1, 1] == 8.0
    assert f.data[6, 6] == 48.0
    assert np.array_equal(f.interior, interior)


# -- schema ---------------------------------------------------------------


def test_field_schema_canonical() -> None:
    assert DEFAULT_HALO == 1
    assert FIELD_NAMES == (
        "altitude", "temperature", "humidity", "precipitation", "biome_id",
    )
    names = [spec.name for spec in FIELD_SCHEMA]
    assert names == [
        "altitude", "temperature", "humidity", "precipitation", "biome_id",
    ]
    biome_spec = [s for s in FIELD_SCHEMA if s.name == "biome_id"][0]
    assert biome_spec.dtype == np.dtype(np.int64)
    assert biome_spec.default == 0
    temp_spec = [s for s in FIELD_SCHEMA if s.name == "temperature"][0]
    assert temp_spec.dtype == np.dtype(np.float64)
    assert temp_spec.default == 25.0
    precip_spec = [s for s in FIELD_SCHEMA if s.name == "precipitation"][0]
    assert precip_spec.dtype == np.dtype(np.float64)
    assert precip_spec.default == 0.0
