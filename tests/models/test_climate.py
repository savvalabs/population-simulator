"""Unit tests for the provisional climate equation (:mod:`population_engine.models.climate`).

These exercise :class:`ClimateModel.step` over *synthetic* arrays — no World,
no Clock, no DataRegistry — proving the model is world/data/ECS-free at runtime
and that its provisional deterministic behaviour (CORE_DESIGN §3.1 / §5.2 / §9,
D2–D5 intentionally open) holds:

* every provisional constant lives in :class:`ClimateParams` (one place) and is
  pinned at its documented value;
* determinism: identical inputs + identical seed → bit-identical outputs;
* the altitude-lapse direction (D2), discrete-season effect (D3), RNG noise
  presence (D4), and clamping/bounds (D5) behave as the provisional spec states;
* unknown season labels fall back to neutral defaults (provisional assumption);
* outputs are fresh ``float64`` arrays, never aliased to inputs;
* the ``models`` package does not import the ``world`` / ``ecs`` / ``core`` /
  ``data`` layers at runtime (CORE_DESIGN §1.2 / §8 layer purity).

The exact provisional constants are referenced by their *literal* values in the
expected-array assertions so changing a :class:`ClimateParams` default surfaces
here as a failure — i.e. the constants are pinned, not painted over by a
copy of the equation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from population_engine.models.climate import ClimateModel, ClimateParams
import population_engine.models as models_pkg


# -- the constants live in one place, pinned at their documented values --------


_GR = 6.5e-3  # Γ = 0.0065 °C/m — the standard-atmosphere lapse rate


def test_climateparams_is_frozen() -> None:
    p = ClimateParams()
    with pytest.raises(Exception):
        p.temperature_lapse_c_per_m = 1.0  # type: ignore[misc]


def test_default_constants_pinned() -> None:
    p = ClimateParams()
    assert p.temperature_lapse_c_per_m == pytest.approx(_GR)
    assert p.season_temperature_offset_c == {"dry": 0.0, "rainy": -2.0}
    assert p.season_humidity_delta == {"dry": 0.0, "rainy": 0.1}
    assert p.season_precipitation_multiplier == {"dry": 0.5, "rainy": 1.5}
    assert p.temperature_noise_sigma == 1.0
    assert p.humidity_noise_sigma == 0.05
    assert p.precipitation_noise_sigma == 0.05
    assert p.humidity_min == 0.0 and p.humidity_max == 1.0
    assert p.precipitation_floor == 0.0
    # The per-season tables above are the single source of the authored
    # constants. The unknown-season neutral fallback (0.0 additive / 1.0
    # multiplicative) is exercised through ``ClimateModel.step`` in
    # ``test_step_unknown_season_is_neutral``; ClimateParams exposes the tables
    # directly (no shadowing accessor methods -- see the model's lookup comment).


# -- determinism: same seed → identical; different seed → different -----------


def _inputs(shape=(4, 4), alt=1200.0):
    return {
        "altitude": np.full(shape, float(alt)),
        "base_temperature": np.full(shape, 20.0),
        "base_humidity": np.full(shape, 0.5),
        "base_precipitation": np.full(shape, 1.0),
    }


def test_step_determinism_same_seed() -> None:
    m = ClimateModel()  # default sigmas (incl. temperature_noise_sigma=1.0)
    t1, h1, p1 = m.step(season="rainy", rng=np.random.default_rng(7), **_inputs())
    t2, h2, p2 = m.step(season="rainy", rng=np.random.default_rng(7), **_inputs())
    assert np.array_equal(t1, t2)
    assert np.array_equal(h1, h2)
    assert np.array_equal(p1, p2)


def test_step_determinism_different_seed_changes_temperature() -> None:
    m = ClimateModel()
    t1, _, _ = m.step(season="rainy", rng=np.random.default_rng(7), **_inputs())
    t2, _, _ = m.step(season="rainy", rng=np.random.default_rng(8), **_inputs())
    assert not np.array_equal(t1, t2)


# -- D2: altitude-lapse direction (linear, temperature-only; provisional) ----


def _quiet():
    """Params with all noise σ=0 → the equation is exact (no stochastic term)."""
    return ClimateParams(
        temperature_noise_sigma=0.0,
        humidity_noise_sigma=0.0,
        precipitation_noise_sigma=0.0,
    )


def test_step_temperature_lapse_linear_and_pinned() -> None:
    m = ClimateModel(_quiet())
    alt = np.array([[0.0, 1000.0]])
    base = np.full((1, 2), 20.0)
    t, _, _ = m.step(
        altitude=alt,
        base_temperature=base,
        base_humidity=np.full_like(base, 0.5),
        base_precipitation=np.full_like(base, 1.0),
        season="dry",                 # dry offset == 0.0 → cancels out
        rng=np.random.default_rng(0),
    )
    expected = base + 0.0 - _GR * alt   # same float ops, in the same order, as the model
    assert np.array_equal(t, expected)
    # directional + pinned: altitude 0 == base; higher altitude is colder.
    assert t[0, 0] == 20.0
    assert t[0, 1] == pytest.approx(20.0 - _GR * 1000.0)
    assert t[0, 1] < t[0, 0]


def test_step_lapse_uses_the_param_not_a_hardcoded_magic() -> None:
    # A doubled Gamma must give double the cooling — proves the model reads
    # params.temperature_lapse_c_per_m rather than an internal literal.
    m = ClimateModel(
        ClimateParams(temperature_lapse_c_per_m=2 * _GR, temperature_noise_sigma=0.0)
    )
    t, _, _ = m.step(
        altitude=np.array([[100.0]]),
        base_temperature=np.array([[20.0]]),
        base_humidity=np.array([[0.5]]),
        base_precipitation=np.array([[1.0]]),
        season="dry",
        rng=np.random.default_rng(0),
    )
    assert t[0, 0] == pytest.approx(20.0 - 2 * _GR * 100.0)


def test_step_humidity_and_precipitation_have_no_altitude_term() -> None:
    # Provisional D2: only temperature depends on altitude. A flat vs a steep
    # altitude must yield identical humidity/precipitation (σ=0, same seed).
    m = ClimateModel(_quiet())
    flat = m.step(season="dry", rng=np.random.default_rng(0), **_inputs(alt=0.0))
    steep = m.step(season="dry", rng=np.random.default_rng(0), **_inputs(alt=4000.0))
    assert np.array_equal(flat[1], steep[1])
    assert np.array_equal(flat[2], steep[2])
    # ...and the temperatures must differ.
    assert not np.array_equal(flat[0], steep[0])


# -- D3: discrete-season effect (additive temp/humidity; multiplicative precip)


def test_step_season_effect_temperature_additive_pinned() -> None:
    m = ClimateModel(_quiet())
    base_t = np.full((2, 2), 20.0)
    base_h = np.full((2, 2), 0.5)
    base_p = np.full((2, 2), 1.0)
    flat_alt = np.zeros((2, 2))
    kw = dict(base_temperature=base_t, base_humidity=base_h,
              base_precipitation=base_p, altitude=flat_alt,
              rng=np.random.default_rng(0))
    dry_t, _dh, _dp = m.step(season="dry", **kw)
    rainy_t, _rh, _rp = m.step(season="rainy", **kw)
    # dry: offset +0.0 → == base; rainy: offset -2.0 → base - 2.0.
    assert np.array_equal(dry_t, base_t)
    assert np.array_equal(rainy_t, base_t - 2.0)


def test_step_season_effect_humidity_additive_pinned() -> None:
    m = ClimateModel(_quiet())
    base_h = np.full((3, 3), 0.5)      # 0.5 + 0.1 == 0.6 — inside [0,1], no clip
    kw = dict(base_temperature=np.zeros((3, 3)), base_humidity=base_h,
              base_precipitation=np.zeros((3, 3)), altitude=np.zeros((3, 3)),
              rng=np.random.default_rng(0))
    _, dry_h, _ = m.step(season="dry", **kw)
    _, rainy_h, _ = m.step(season="rainy", **kw)
    assert np.array_equal(dry_h, base_h)            # dry delta == 0.0
    assert np.array_equal(rainy_h, base_h + 0.1)    # rainy delta == +0.1


def test_step_season_effect_precipitation_multiplicative_pinned() -> None:
    m = ClimateModel(_quiet())
    base_p = np.full((3, 3), 1.0)
    kw = dict(base_temperature=np.zeros((3, 3)), base_humidity=np.full((3, 3), 0.5),
              base_precipitation=base_p, altitude=np.zeros((3, 3)),
              rng=np.random.default_rng(0))
    _, _, dry_p = m.step(season="dry", **kw)
    _, _, rainy_p = m.step(season="rainy", **kw)
    assert np.array_equal(dry_p, base_p * 0.5)      # dry multiplier == 0.5
    assert np.array_equal(rainy_p, base_p * 1.5)    # rainy multiplier == 1.5


def test_step_unknown_season_is_neutral() -> None:
    # A calendar producing a label the maps don't know must not crash and must
    # fall back to neutral defaults (offset 0, delta 0, multiplier 1.0).
    m = ClimateModel(_quiet())
    t, h, p = m.step(
        altitude=np.zeros((1, 1)),
        base_temperature=np.array([[20.0]]),
        base_humidity=np.array([[0.5]]),
        base_precipitation=np.array([[2.0]]),
        season="monsoon",
        rng=np.random.default_rng(0),
    )
    assert t[0, 0] == 20.0      # base - 0 + 0 + 0
    assert h[0, 0] == 0.5       # base + 0 + 0
    assert p[0, 0] == 2.0       # base * 1.0 + 0


def test_step_dry_and_rainy_outputs_differ() -> None:
    # Sanity: the discrete seasons are not no-ops; with default noise the two
    # seasons produce different quantities (seed-equal RNG draws throughout).
    m = ClimateModel()
    t_d, h_d, p_d = m.step(season="dry", rng=np.random.default_rng(1), **_inputs())
    t_r, h_r, p_r = m.step(season="rainy", rng=np.random.default_rng(1), **_inputs())
    assert not np.array_equal(t_d, t_r)
    assert not np.array_equal(h_d, h_r)
    assert not np.array_equal(p_d, p_r)


# -- D4: RNG noise is present and shaped ----------------------------------


def test_step_noise_present_when_sigma_nonzero() -> None:
    m = ClimateModel()  # temperature_noise_sigma == 1.0 by default
    t, _, _ = m.step(season="dry", rng=np.random.default_rng(0), **_inputs(alt=0.0))
    # σ=1.0 over 16 cells → draws are essentially never all exactly the mean.
    assert not np.all(t == 20.0)


def test_step_noise_shape_matches_altitude() -> None:
    m = ClimateModel()
    for shape in [(1, 1), (2, 3), (8, 8)]:
        t, h, p = m.step(season="rainy", rng=np.random.default_rng(0),
                         **_inputs(shape=shape))
        assert t.shape == shape
        assert h.shape == shape
        assert p.shape == shape


# -- D5: clamping / bounds -------------------------------------------------


def test_step_humidity_is_in_unit_interval() -> None:
    params = ClimateParams(humidity_noise_sigma=2.0)  # huge σ → draws outside [0,1]
    m = ClimateModel(params)
    _, h, _ = m.step(season="rainy", rng=np.random.default_rng(123),
                     **_inputs(shape=(100, 100)))
    assert h.min() >= 0.0
    assert h.max() <= 1.0


def test_step_humidity_clamps_at_saturation() -> None:
    params = ClimateParams(humidity_noise_sigma=5.0)
    m = ClimateModel(params)
    _, h, _ = m.step(
        season="rainy", rng=np.random.default_rng(9),
        altitude=np.zeros((50, 50)),
        base_temperature=np.zeros((50, 50)),
        base_humidity=np.full((50, 50), 0.95),   # +0.1 season + σ=5 → saturates
        base_precipitation=np.zeros((50, 50)),
    )
    assert h.max() == pytest.approx(1.0)
    assert h.min() >= 0.0


def test_step_precipitation_is_non_negative() -> None:
    params = ClimateParams(precipitation_noise_sigma=1.0)  # base 0 ± 1.0
    m = ClimateModel(params)
    _, _, p = m.step(
        season="dry", rng=np.random.default_rng(321),
        altitude=np.zeros((100, 100)),
        base_temperature=np.zeros((100, 100)),
        base_humidity=np.full((100, 100), 0.5),
        base_precipitation=np.zeros((100, 100)),
    )
    assert p.min() >= 0.0
    # With σ=1.0 over 10_000 cells, many draws go negative pre-floor → at least
    # some cells must be pinned exactly at the floor.
    assert (p == 0.0).any()


def test_step_precipitation_floor_pinned_at_param() -> None:
    # The non-negative floor is the param's precipitation_floor, not a hardcoded 0.
    params = ClimateParams(
        precipitation_floor=2.0,
        precipitation_noise_sigma=1.0,
        season_precipitation_multiplier={"dry": 1.0, "rainy": 1.0},
    )
    m = ClimateModel(params)
    _, _, p = m.step(
        season="dry", rng=np.random.default_rng(55),
        altitude=np.zeros((50, 50)),
        base_temperature=np.zeros((50, 50)),
        base_humidity=np.full((50, 50), 0.5),
        base_precipitation=np.zeros((50, 50)),
    )
    assert p.min() >= 2.0
    assert (p == 2.0).any()


# -- outputs: dtype, shape, aliasing --------------------------------------


def test_step_outputs_are_float64() -> None:
    m = ClimateModel()
    t, h, p = m.step(season="rainy", rng=np.random.default_rng(0), **_inputs())
    assert t.dtype == np.dtype(np.float64)
    assert h.dtype == np.dtype(np.float64)
    assert p.dtype == np.dtype(np.float64)


def test_step_promotes_non_float64_inputs_to_float64() -> None:
    # The climate-Field contract is float64; a provider handing float32 still
    # gets float64 back (the model pins the dtype, copy=False on the hot path).
    m = ClimateModel()
    arr = lambda v: np.full((2, 2), v, dtype=np.float32)
    t, h, p = m.step(
        altitude=arr(100.0),
        base_temperature=arr(20.0),
        base_humidity=arr(0.5),
        base_precipitation=arr(1.0),
        season="dry",
        rng=np.random.default_rng(0),
    )
    assert t.dtype == np.dtype(np.float64)
    assert h.dtype == np.dtype(np.float64)
    assert p.dtype == np.dtype(np.float64)


def test_step_outputs_do_not_alias_inputs() -> None:
    m = ClimateModel()
    bt = np.full((2, 2), 20.0)
    bh = np.full((2, 2), 0.5)
    bp = np.full((2, 2), 1.0)
    t, h, p = m.step(season="dry", rng=np.random.default_rng(0),
                     altitude=np.full((2, 2), 100.0),
                     base_temperature=bt, base_humidity=bh, base_precipitation=bp)
    # mutating an output must not touch the input it derived from.
    t[0, 0] = -999.0
    h[0, 0] = -999.0
    p[0, 0] = -999.0
    assert bt[0, 0] == 20.0
    assert bh[0, 0] == 0.5
    assert bp[0, 0] == 1.0
    assert not np.shares_memory(t, bt)
    assert not np.shares_memory(h, bh)
    assert not np.shares_memory(p, bp)


def test_step_does_not_mutate_inputs() -> None:
    m = ClimateModel()
    alt = np.full((2, 2), 100.0)
    bt = np.full((2, 2), 20.0)
    bh = np.full((2, 2), 0.5)
    bp = np.full((2, 2), 1.0)
    snapshots = (alt.copy(), bt.copy(), bh.copy(), bp.copy())
    m.step(season="rainy", rng=np.random.default_rng(0),
           altitude=alt, base_temperature=bt, base_humidity=bh, base_precipitation=bp)
    assert np.array_equal(alt, snapshots[0])
    assert np.array_equal(bt, snapshots[1])
    assert np.array_equal(bh, snapshots[2])
    assert np.array_equal(bp, snapshots[3])


# -- layer purity: models/ imports no world / ecs / core / data at runtime ----


_FORBIDDEN_LAYER_PACKAGES = ("world", "ecs", "core", "data")


def _runtime_forbidden_imports(path: Path) -> list[str]:
    """Runtime imports of forbidden population_engine layers in *path*.

    Imports under ``if TYPE_CHECKING:`` are allowed (never execute). Any other
    ``import world`` / ``from population_engine.ecs import ...`` / relative
    ``from .. ecs ...`` reference is a violation: the models layer must stay
    world/ecs/core/data-free at runtime (CORE_DESIGN §1.2 / §8).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad: list[str] = []

    def _is_forbidden(name: str) -> bool:
        parts = name.split(".")
        if len(parts) >= 2 and parts[0] == "population_engine":
            return parts[1] in _FORBIDDEN_LAYER_PACKAGES
        return name in _FORBIDDEN_LAYER_PACKAGES

    def _imported_names(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Import):
            return [a.name for a in node.names]
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            return [mod] if mod else []
        return []

    def _is_type_checking(test: ast.expr) -> bool:
        return (
            isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
        ) or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )

    def visit(stmts: list[ast.stmt], guarded: bool) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                if _is_type_checking(stmt.test):
                    visit(stmt.orelse, guarded)
                else:
                    visit(stmt.body, guarded)
                    visit(stmt.orelse, guarded)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if not guarded:
                    for name in _imported_names(stmt):
                        if _is_forbidden(name):
                            seg = ast.get_source_segment(tree, stmt) or "<import>"
                            bad.append(f"{path.name}:{stmt.lineno}: {seg}")
            else:
                for fld in ("body", "orelse", "finalbody"):
                    seq = getattr(stmt, fld, None)
                    if isinstance(seq, list):
                        visit(seq, guarded)

    visit(tree.body, guarded=False)
    return bad


def test_models_package_imports_no_world_ecs_core_data_at_runtime() -> None:
    pkg_dir = Path(models_pkg.__file__).resolve().parent
    py_files = sorted(pkg_dir.glob("*.py"))
    assert py_files, "expected models/ python modules to scan"
    violations: list[str] = []
    for f in py_files:
        violations.extend(_runtime_forbidden_imports(f))
    assert not violations, (
        "models/ must not import world/ecs/core/data at runtime:\n"
        + "\n".join(violations)
    )
