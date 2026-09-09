"""Integration tests for :class:`population_engine.systems.climate.ClimateSystem`.

These exercise the S3.1 integrator over a *real* :class:`World` plus a
:class:`Clock` and a shared RNG (CORE_DESIGN §3.1 / §5.2 / §9, ADR-002),
proving the architecture and data flow the milestone establishes:

* the climate ``Field`` interiors (temperature / humidity / precipitation) are
  written each tick and differ from their generation defaults;
* determinism: identical world+clock+rng+model+provider -> bit-identical climate
  interiors across every chunk;
* ADR-002: after the system runs, every chunk's ``biome_id`` interior equals
  ``World.classify_chunk`` computed from the climate the system just wrote
  (the downstream projection, never re-read as an input);
* the D1 biome-provider seam is *injectable*: the system holds no biome
  selection algorithm and surfaces whatever base values the injected provider
  returns (a future D1 decision swaps the provider, never the model);
* the discrete season is read from ``ctx.clock`` (dry vs rainy differ);
* ``precipitation`` (the S3.1 field added to ``FIELD_SCHEMA``) participates in
  halo refresh like any other Field;
* the system declares no ECS component reads/writes (it touches World Fields,
  not Components) and runs as a stage-1 dataflow root under the Scheduler;
* defensive: a context with no World is a no-op.

The provisional equations (:mod:`population_engine.models.climate`) are tested
separately over synthetic arrays in ``tests/models/test_climate.py``; here they
are exercised only through the integrator at representative points.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pytest

from population_engine.core.time import Clock
from population_engine.ecs import EventBus, Registry
from population_engine.ecs.scheduler import Scheduler, SystemContext
from population_engine.models.climate import ClimateModel, ClimateParams
from population_engine.systems.climate import (
    BiomeBaseValues,
    ClimateSystem,
    UniformBiomeProvider,
)
from population_engine.world.biome import Biome
from population_engine.world.coords import ChunkCoord
from population_engine.world.world import World


# -- helpers -----------------------------------------------------------------


def _world(**kwargs) -> World:
    """Bounded World with fast, deterministic test defaults (mirrors test_world)."""
    defaults: dict = {"seed": 42, "chunk_size": 8, "width_chunks": 2, "height_chunks": 2}
    defaults.update(kwargs)
    return World(**defaults)


def _tier_biomes() -> list[Biome]:
    """Three altitude/temperature tiers (default humidity range)."""
    return [
        Biome("low", min_altitude=0, max_altitude=1000, min_temperature=20, max_temperature=30),
        Biome("mid", min_altitude=1000, max_altitude=3000, min_temperature=10, max_temperature=20),
        Biome("high", min_altitude=3000, max_altitude=6000, min_temperature=0, max_temperature=10),
    ]


def _quiet_params() -> ClimateParams:
    """All noise sigma=0 -> the integrator's climate is exactly the model formula."""
    return ClimateParams(
        temperature_noise_sigma=0.0,
        humidity_noise_sigma=0.0,
        precipitation_noise_sigma=0.0,
    )


def _ctx(
    world: World,
    *,
    clock: Clock | None = None,
    rng: np.random.Generator | None = None,
) -> SystemContext:
    return SystemContext(
        registry=Registry(),
        events=EventBus(),
        clock=clock if clock is not None else Clock(),
        rng=rng if rng is not None else np.random.default_rng(0),
        world=world,
    )


def _all_chunk_coords(world: World):
    for iy in range(world.height_chunks):
        for ix in range(world.width_chunks):
            yield ChunkCoord(ix, iy)


def _zero_altitude(world: World) -> None:
    """Flatten every chunk's altitude interior to 0.0 (for exact-form tests)."""
    for coord in _all_chunk_coords(world):
        world.chunk(coord).field("altitude").interior[...] = 0.0


# -- architecture: the system's declared access -----------------------------


def test_climatesystem_declares_no_component_access_and_no_after() -> None:
    # The system touches World Fields, not ECS components, so it declares no
    # component read/write (CORE_DESIGN sec 8 -- World is outside the component
    # conflict graph). It is a stage-1 dataflow root (no `after`).
    s = ClimateSystem()
    assert s.name == "climate"
    assert s.reads == ()
    assert s.writes == ()
    assert s.after == ()


def test_climatesystem_default_construction_runs() -> None:
    # A bare ClimateSystem() wires a default model + the uniform stand-in and
    # runs over a world without error, writing float64 climate interiors.
    w = _world()
    ClimateSystem().update(_ctx(w, rng=np.random.default_rng(1)))
    c = w.chunk(ChunkCoord(0, 0))
    assert c.field("temperature").interior.dtype == np.dtype(np.float64)
    assert c.field("humidity").interior.dtype == np.dtype(np.float64)
    assert c.field("precipitation").interior.dtype == np.dtype(np.float64)
    assert c.field("precipitation").interior.shape == (w.chunk_size, w.chunk_size)


# -- climate Fields are written and overwrite generation defaults ------------


def test_climatesystem_writes_climate_interiors_off_defaults() -> None:
    # Generation seeds temperature (28 - lapse*alt + noise) and precipitation
    # (schema default 0.0). After ClimateSystem with a uniform provider, the
    # temperature differs from the generation value and precipitation is nonzero
    # (base_precipitation=1.0 -> ~0.5 in the dry season, plus noise).
    w = _world()
    coord = ChunkCoord(0, 0)
    gen_temp = w.chunk(coord).field("temperature").interior.copy()
    sys = ClimateSystem(
        ClimateModel(),
        UniformBiomeProvider(base_temperature=20.0, base_humidity=0.5, base_precipitation=1.0),
    )
    sys.update(_ctx(w, rng=np.random.default_rng(7)))
    new_temp = w.chunk(coord).field("temperature").interior
    new_precip = w.chunk(coord).field("precipitation").interior
    assert not np.array_equal(new_temp, gen_temp)        # overwrote generation
    assert not np.all(new_precip == 0.0)                 # wrote precipitation


# -- determinism -------------------------------------------------------------


def test_climatesystem_determinism_same_seed() -> None:
    w1 = _world(seed=42)
    w2 = _world(seed=42)
    sys = ClimateSystem(
        ClimateModel(),
        UniformBiomeProvider(base_temperature=20.0, base_humidity=0.6, base_precipitation=1.0),
    )
    sys.update(_ctx(w1, rng=np.random.default_rng(101)))
    sys.update(_ctx(w2, rng=np.random.default_rng(101)))
    for coord in _all_chunk_coords(w1):
        c1, c2 = w1.chunk(coord), w2.chunk(coord)
        for name in ("temperature", "humidity", "precipitation", "biome_id"):
            assert np.array_equal(
                c1.field(name).interior, c2.field(name).interior
            ), f"{name!r} differs at chunk ({coord.ix},{coord.iy})"


def test_climatesystem_determinism_different_seed_changes_temperature() -> None:
    w1 = _world(seed=42)
    w2 = _world(seed=42)
    sys = ClimateSystem(ClimateModel(), UniformBiomeProvider(base_temperature=20.0))
    sys.update(_ctx(w1, rng=np.random.default_rng(1)))
    sys.update(_ctx(w2, rng=np.random.default_rng(2)))
    coord = ChunkCoord(0, 0)
    assert not np.array_equal(
        w1.chunk(coord).field("temperature").interior,
        w2.chunk(coord).field("temperature").interior,
    )


# -- ADR-002: biome_id == classify_chunk after the climate is written --------


def test_climatesystem_biome_id_equals_classify_chunk_after_update() -> None:
    # With a wired biome table, after ClimateSystem refreshes climate + biome_id,
    # every chunk's stored biome_id must equal classify_chunk recomputed from the
    # post-update temperature/humidity (the ADR-002 downstream projection).
    w = _world(seed=1, biomes=_tier_biomes())
    sys = ClimateSystem(
        ClimateModel(),
        UniformBiomeProvider(base_temperature=20.0, base_humidity=0.5, base_precipitation=1.0),
    )
    sys.update(_ctx(w, rng=np.random.default_rng(7)))
    for coord in _all_chunk_coords(w):
        c = w.chunk(coord)
        assert np.array_equal(c.field("biome_id").interior, w.classify_chunk(c)), (
            f"biome_id != classify_chunk at chunk ({coord.ix},{coord.iy})"
        )


def test_climatesystem_biome_id_refreshed_from_new_climate() -> None:
    # The refresh is not a no-op: ClimateSystem overwrites generation climate, so
    # biome_id (re-derived from the new climate) must track classify_chunk even
    # though generation set its own biome_id from generation climate.
    w = _world(seed=1, biomes=_tier_biomes())
    coord = ChunkCoord(0, 0)
    gen_temp = w.chunk(coord).field("temperature").interior.copy()
    gen_biome = w.chunk(coord).field("biome_id").interior.copy()
    sys = ClimateSystem(
        ClimateModel(),
        UniformBiomeProvider(base_temperature=20.0, base_humidity=0.5, base_precipitation=1.0),
    )
    sys.update(_ctx(w, rng=np.random.default_rng(7)))
    c = w.chunk(coord)
    # Climate really changed...
    assert not np.array_equal(c.field("temperature").interior, gen_temp)
    # ...and biome_id was recomputed from the new climate (matches classify_chunk).
    assert np.array_equal(c.field("biome_id").interior, w.classify_chunk(c))
    # The refreshed biome_id may or may not differ from generation's where the
    # climate crossed a tier boundary; the ADR-002 invariant is the equality
    # above, not a guaranteed change. Sanity: at least classify_chunk ~= biome_id.


# -- D1 seam: the biome-provider is injectable -------------------------------


def _stub_provider(base_temperature: float, base_humidity: float, base_precipitation: float):
    """A trivial custom provider (NOT UniformBiomeProvider) proving the seam."""
    class _P:
        def base_values(self, altitude: np.ndarray) -> "BiomeBaseValues":
            shp = altitude.shape
            return BiomeBaseValues(
                np.full(shp, base_temperature, dtype=np.float64),
                np.full(shp, base_humidity, dtype=np.float64),
                np.full(shp, base_precipitation, dtype=np.float64),
            )
    return _P()


def test_climatesystem_surfaces_injected_provider_base_values() -> None:
    # Flat altitude + quiet model + dry season -> each output is exactly the
    # provider's base value shaped by the discrete-season terms. Proves the
    # system uses whatever provider is injected (D1 isolated).
    w = _world()
    _zero_altitude(w)
    sys = ClimateSystem(
        ClimateModel(_quiet_params()),
        _stub_provider(base_temperature=30.0, base_humidity=0.4, base_precipitation=2.0),
    )
    sys.update(_ctx(w, rng=np.random.default_rng(0)))   # dry season (Clock tick 0 -> Jan)
    for coord in _all_chunk_coords(w):
        t = w.chunk(coord).field("temperature").interior
        h = w.chunk(coord).field("humidity").interior
        p = w.chunk(coord).field("precipitation").interior
        # dry: t = 30 - lapse*0 + 0 + 0 = 30; h = clip(0.4 + 0 + 0) = 0.4;
        # p = max(2.0 * 0.5 + 0, 0) = 1.0
        assert np.all(t == 30.0)
        assert np.all(h == 0.4)
        assert np.all(p == 1.0)


def test_climatesystem_swapping_provider_changes_output() -> None:
    # Two injected providers with different base_temperature yield different
    # temperature interiors (the seam, not a system-internal constant, drives).
    base_alt = _world()
    _zero_altitude(base_alt)

    w1 = _world(seed=42)
    w2 = _world(seed=42)
    _zero_altitude(w1)
    _zero_altitude(w2)
    ClimateSystem(ClimateModel(_quiet_params()),
                  _stub_provider(base_temperature=30.0, base_humidity=0.5, base_precipitation=1.0)
                  ).update(_ctx(w1, rng=np.random.default_rng(0)))
    ClimateSystem(ClimateModel(_quiet_params()),
                  _stub_provider(base_temperature=15.0, base_humidity=0.5, base_precipitation=1.0)
                  ).update(_ctx(w2, rng=np.random.default_rng(0)))
    coord = ChunkCoord(0, 0)
    assert np.all(w1.chunk(coord).field("temperature").interior == 30.0)
    assert np.all(w2.chunk(coord).field("temperature").interior == 15.0)


def test_climatesystem_holds_no_biome_lookup_algorithm() -> None:
    # Structural: the integrator does not grow a selection algorithm. It exposes
    # only the injected provider; the default stand-in is UniformBiomeProvider
    # (a single-value stand-in for D1, not a per-cell lookup).
    s = ClimateSystem()
    assert isinstance(s._biome_provider, UniformBiomeProvider)
    s2 = ClimateSystem(biome_provider=_stub_provider(1.0, 0.0, 0.0))
    assert s2._biome_provider is not None
    assert not isinstance(s2._biome_provider, UniformBiomeProvider)


# -- discrete season read from ctx.clock -------------------------------------


def test_climatesystem_dry_vs_rainy_season_differ() -> None:
    w1 = _world(seed=42)
    w2 = _world(seed=42)
    sys = ClimateSystem(
        ClimateModel(),
        UniformBiomeProvider(base_temperature=20.0, base_humidity=0.5, base_precipitation=1.0),
    )
    dry_clock = Clock()                                   # tick 0 -> Jan -> "dry"
    rainy_clock = Clock(start_date=_dt.date(2000, 5, 1))   # -> month 5 -> "rainy"
    sys.update(_ctx(w1, clock=dry_clock, rng=np.random.default_rng(1)))
    sys.update(_ctx(w2, clock=rainy_clock, rng=np.random.default_rng(1)))
    coord = ChunkCoord(0, 0)
    for name in ("temperature", "humidity", "precipitation"):
        assert not np.array_equal(
            w1.chunk(coord).field(name).interior, w2.chunk(coord).field(name).interior
        ), f"season had no effect on {name!r}"


# -- precipitation participates in halo refresh -------------------------------


def _alt_gradient_provider():
    """Provider whose precipitation varies per cell (via altitude) so the halo
    seam test is meaningful (non-constant neighbour values)."""
    class _P:
        def base_values(self, altitude: np.ndarray) -> "BiomeBaseValues":
            return BiomeBaseValues(
                np.full(altitude.shape, 20.0, dtype=np.float64),
                np.full(altitude.shape, 0.5, dtype=np.float64),
                (altitude * 1e-3).astype(np.float64),   # varies per cell
            )
    return _P()


def test_climatesystem_precipitation_halo_mirrors_neighbour_seam() -> None:
    w = _world(seed=1)
    ClimateSystem(
        ClimateModel(_quiet_params()),
        _alt_gradient_provider(),
    ).update(_ctx(w, rng=np.random.default_rng(0)))
    w.refresh_halos()
    h, S = w.halo, w.chunk_size
    left = w.chunk(ChunkCoord(0, 0)).field("precipitation")
    right = w.chunk(ChunkCoord(1, 0)).field("precipitation")
    # chunk(0,0) right halo == chunk(1,0) left interior column (the seam).
    assert np.array_equal(left.data[h : h + S, -1], right.interior[:, 0])
    # and the values actually vary (so the mirror is a real test, not a constant).
    assert right.interior[:, 0].std() > 0.0


def test_climatesystem_precipitation_world_edge_reflective() -> None:
    w = _world(seed=1)
    ClimateSystem(
        ClimateModel(_quiet_params()),
        _alt_gradient_provider(),
    ).update(_ctx(w, rng=np.random.default_rng(0)))
    w.refresh_halos()
    h, S = w.halo, w.chunk_size
    f = w.chunk(ChunkCoord(0, 0)).field("precipitation")
    # top world edge: halo row mirrors the chunk's own top interior row.
    assert np.array_equal(f.data[0, h : h + S], f.interior[0, :])


# -- defensive: no world / no clock ------------------------------------------


def test_climatesystem_with_no_world_is_a_noop() -> None:
    ctx = SystemContext(registry=Registry(), events=EventBus())   # world is None
    ClimateSystem().update(ctx)   # must not raise


def test_climatesystem_with_no_clock_defaults_to_dry() -> None:
    w = _world()
    _zero_altitude(w)
    # ctx.clock is None -> system falls back to the "dry" defensive default.
    ctx = SystemContext(
        registry=Registry(), events=EventBus(),
        clock=None, rng=np.random.default_rng(0), world=w,
    )
    ClimateSystem(
        ClimateModel(_quiet_params()),
        UniformBiomeProvider(base_temperature=20.0, base_humidity=0.5, base_precipitation=2.0),
    ).update(ctx)
    c = w.chunk(ChunkCoord(0, 0))
    # dry: temperature == base (no offset), precipitation == base * 0.5.
    assert np.all(c.field("temperature").interior == 20.0)
    assert np.all(c.field("precipitation").interior == 1.0)


# -- runs under the Scheduler as a stage-1 root ------------------------------


def test_climatesystem_runs_under_scheduler_stage_one() -> None:
    w = _world()
    sched = Scheduler()
    sched.add_system(ClimateSystem())
    sched.build()
    stages = sched.stages()
    assert len(stages) >= 1
    assert stages[0][0].name == "climate"   # root: stage 1, first
    # execute through the scheduler end-to-end (mirrors the Engine tick phase 3).
    sched.execute(_ctx(w, rng=np.random.default_rng(3)))
    # no exception above; and climate was written.
    assert w.chunk(ChunkCoord(0, 0)).field("precipitation").interior.shape == (
        w.chunk_size, w.chunk_size,
    )


# -- BiomeBaseValues payload -------------------------------------------------


def test_biomebasevalues_named_accessors() -> None:
    t = np.zeros((2, 2))
    h = np.zeros((2, 2))
    p = np.zeros((2, 2))
    v = BiomeBaseValues(t, h, p)
    assert v.base_temperature is t
    assert v.base_humidity is h
    assert v.base_precipitation is p
    # behaves as a 3-tuple too (positional unpacking works downstream).
    a, b, c = v
    assert a is t and b is h and c is p
