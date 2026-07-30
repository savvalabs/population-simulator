"""S2 gate: the core ECS component layer.

These tests verify the foundational, data-only components introduced in S2
(:mod:`population_engine.ecs.components`) plus the enums in
:mod:`population_engine.ecs.enums`. They assert the architectural contracts of
S2, not simulation behaviour:

* every component subclasses :class:`~population_engine.ecs.Component` and is
  constructible;
* components are data only — plain mutable ``@dataclass`` with no user methods;
* enum values are correct and the ``DietType`` labels match the attributes
  authored in the ``data`` layer's bundled species sources;
* component registration, archetype grouping, and live mutable query results
  behave per the existing ECS conventions;
* ``Reproductive.mate_id`` accepts both an :class:`Entity` and ``None``;
* tuple-typed defaults stay immutable (no shared mutable default);
* no runtime import from the World layer is introduced in ``ecs/``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path

import pytest

import population_engine.ecs as ecs_pkg
from population_engine.ecs import (
    Age,
    AgeStage,
    CellExposure,
    Component,
    Diet,
    DietType,
    Entity,
    EntityAllocator,
    MovementLog,
    MovementState,
    Position,
    Query,
    Registry,
    Reproductive,
    Sex,
    SpeciesRef,
    Vitals,
)
from population_engine.data import load_default_registry


# The complete core component set, in CORE_DESIGN §5.1 declaration order.
CORE_COMPONENTS = (
    SpeciesRef,
    Position,
    Vitals,
    Age,
    Reproductive,
    Diet,
    MovementLog,
    CellExposure,
)

CORE_ENUMS = (AgeStage, DietType, MovementState, Sex)


# -- component identity & construction ---------------------------------------


def test_every_component_subclasses_component() -> None:
    for c in CORE_COMPONENTS:
        assert issubclass(c, Component), f"{c!r} must subclass Component"


def test_every_component_is_a_plain_mutable_dataclass() -> None:
    for c in CORE_COMPONENTS:
        assert is_dataclass(c), f"{c!r} must be a @dataclass"
        inst = c()
        # Mutable: a frozen dataclass raises FrozenInstanceError on setattr.
        first = next(iter(fields(inst)))
        setattr(inst, first.name, getattr(inst, first.name))
        assert is_dataclass(inst)


def test_every_component_constructible_with_no_args() -> None:
    for c in CORE_COMPONENTS:
        inst = c()  # construction-convention: all fields defaulted
        assert isinstance(inst, c)
        assert isinstance(inst, Component)


def test_every_component_field_is_overridable() -> None:
    # "Provide default values for every field" — every field must also accept
    # an explicit constructor argument.
    for c in CORE_COMPONENTS:
        kwargs = {f.name: _example_value(f) for f in fields(c)}
        inst = c(**kwargs)
        for f in fields(inst):
            assert getattr(inst, f.name) == kwargs[f.name], (c, f.name)


def _example_value(f) -> object:
    """A non-default value of a plausible type for field ``f``."""
    name = f.name
    # Entity | None
    if name == "mate_id":
        return EntityAllocator().allocate()
    # enum-typed fields, by name
    if name == "sex":
        return Sex.FEMALE
    if name == "stage":
        return AgeStage.MATURE
    if name == "diet_type":
        return DietType.CARNIVORE
    if name == "state":
        return MovementState.FORAGE
    if name == "consumes":
        return ("grass", "rabbit")
    # ints
    if name in {"x", "y", "age_ticks", "gestation_ticks",
                "parental_care_ticks", "biome_id"}:
        return 7
    # floats
    if name in {"hunger", "thirst", "energy", "hp",
                "distance_this_tick", "temperature", "humidity",
                "biomass", "water"}:
        return 3.5
    # strings
    if name == "species_id":
        return "jaguar"
    raise AssertionError(f"no example value for {name!r} on {f}")  # pragma: no cover


# -- data-only: no user methods (source-level AST check) --------------------


def _component_module_path() -> Path:
    # ``components`` is defined in its own module alongside the ecs package.
    from population_engine.ecs import components as _components_mod

    return Path(_components_mod.__file__).resolve()


def test_components_define_no_user_methods() -> None:
    """Components are data only: their source bodies contain no ``def``."""
    tree = ast.parse(_component_module_path().read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name not in {c.__name__ for c in CORE_COMPONENTS}:
            continue
        offenders = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
        assert not offenders, (
            f"{node.name} must be data-only but defines methods: {offenders}"
        )


def test_components_use_plain_dataclass_decorator() -> None:
    tree = ast.parse(_component_module_path().read_text(encoding="utf-8"))
    comp_names = {c.__name__ for c in CORE_COMPONENTS}
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in comp_names:
            continue
        decs = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                decs.append(d.id)
            elif isinstance(d, ast.Attribute):
                decs.append(d.attr)
        assert "dataclass" in decs, f"{node.name} must use @dataclass"
        found.add(node.name)
    assert found == comp_names


# -- enums -------------------------------------------------------------------


@pytest.mark.parametrize("enum", CORE_ENUMS, ids=lambda e: e.__name__)
def test_enums_are_str_enums(enum) -> None:
    assert issubclass(enum, str)
    assert issubclass(enum, Enum)
    for member in enum:
        assert isinstance(member, str)
        assert member.value == member  # str-Enum: the member IS its value
        assert enum(member.value) is member  # value → same member


def test_sex_values() -> None:
    assert {m.value for m in Sex} == {"male", "female"}


def test_age_stage_values() -> None:
    assert {m.value for m in AgeStage} == {"juvenile", "mature", "senescent"}


def test_movement_state_values() -> None:
    assert {m.value for m in MovementState} == {"forage", "flee", "migrate", "rest"}


def test_diet_type_values() -> None:
    assert {m.value for m in DietType} == {
        "herbivore", "carnivore", "omnivore", "scavenger",
    }


def test_diet_type_matches_bundled_species_data() -> None:
    """Every ``diet_type`` label authored in the data layer is a DietType member.

    This is the cross-layer contract: the ``(str, Enum)`` value mirrors the
    identifiers stored in the data layer, so a component's ``Diet.diet_type``
    compares directly against a ``SpeciesData.diet_type`` string.
    """
    reg = load_default_registry()
    bundled = {s.diet_type for s in reg.all_species()}
    assert bundled, "bundled species sources must define diet_type"
    member_values = {m.value for m in DietType}
    # Every authored label is a valid DietType member...
    assert bundled <= member_values, bundled - member_values
    # ...and the bundled set matches exactly the core diet kinds.
    assert bundled == {"herbivore", "carnivore", "omnivore", "scavenger"}


# -- registration ------------------------------------------------------------


def test_register_all_core_components_assigns_stable_ids() -> None:
    r = Registry()
    ids = [r.register_component(c) for c in CORE_COMPONENTS]
    assert ids == list(range(len(CORE_COMPONENTS)))
    # idempotent
    assert r.register_component(SpeciesRef) == ids[0]
    assert r.component_types == CORE_COMPONENTS


def test_register_rejects_non_component() -> None:
    r = Registry()
    from population_engine.ecs.errors import ComponentError

    with pytest.raises(ComponentError):
        r.register_component(int)


# -- archetype grouping -----------------------------------------------------


def test_identical_component_sets_share_one_archetype() -> None:
    r = Registry()
    e1 = r.create_entity(SpeciesRef(), Position(), Vitals())
    e2 = r.create_entity(SpeciesRef(), Position(), Vitals())
    assert r.archetype_count == 1
    assert len(r) == 2
    # Both land in the same archetype, returned together by the union query.
    rows = list(r.query(SpeciesRef, Position, Vitals))
    assert {row[0] for row in rows} == {e1, e2}


def test_distinct_component_sets_form_distinct_archetypes() -> None:
    r = Registry()
    r.create_entity(SpeciesRef(), Position())
    r.create_entity(SpeciesRef(), Position(), Diet())
    r.create_entity(SpeciesRef(), Position(), Diet(), MovementLog())
    assert r.archetype_count == 3


def test_archetype_grouping_is_independent_of_constructor_order() -> None:
    r = Registry()
    e1 = r.create_entity(Position(), SpeciesRef())  # reversed order
    e2 = r.create_entity(SpeciesRef(), Position())
    assert r.archetype_count == 1
    assert {h for h, _, _ in r.query(Position, SpeciesRef)} == {e1, e2}


# -- query returns live, mutable component instances -------------------------


def test_query_returns_live_mutable_component_instances() -> None:
    r = Registry()
    e = r.create_entity(Position(x=0, y=0), Vitals(hunger=0.0))
    for _, pos, vitals in r.query(Position, Vitals):
        pos.x = 42
        vitals.hunger = 7.5
    # Mutations through the query are visible via direct lookup — same objects.
    assert r.get_component(e, Position).x == 42
    assert r.get_component(e, Vitals).hunger == 7.5


def test_query_yields_all_core_components_for_a_full_entity() -> None:
    r = Registry()
    e = r.create_entity(*[c() for c in CORE_COMPONENTS])
    q = Query(Position, Diet, Reproductive, Age, CellExposure, MovementLog,
             Vitals, SpeciesRef)
    rows = list(q.iter(r))
    assert len(rows) == 1
    entity, pos, diet, repro, age, exposure, mlog, vitals, sref = rows[0]
    assert entity is e
    for comp, cls in (
        (pos, Position), (diet, Diet), (repro, Reproductive), (age, Age),
        (exposure, CellExposure), (mlog, MovementLog), (vitals, Vitals),
        (sref, SpeciesRef),
    ):
        assert isinstance(comp, cls)


# -- Reproductive.mate_id accepts Entity and None ---------------------------


def test_reproductive_mate_id_accepts_none() -> None:
    assert Reproductive().mate_id is None
    r = Registry()
    e = r.create_entity(Reproductive())
    assert r.get_component(e, Reproductive).mate_id is None


def test_reproductive_mate_id_accepts_entity() -> None:
    mate = EntityAllocator().allocate()
    repro = Reproductive(mate_id=mate)
    assert repro.mate_id == mate
    assert isinstance(repro.mate_id, Entity)
    r = Registry()
    e = r.create_entity(repro)
    assert r.get_component(e, Reproductive).mate_id == mate


def test_reproductive_mate_id_round_trips_entity_and_none() -> None:
    r = Registry()
    e = r.create_entity(Reproductive())
    repro = r.get_component(e, Reproductive)
    assert repro.mate_id is None
    mate = EntityAllocator().allocate()
    repro.mate_id = mate  # mutable; later loading=None re-marks it unpaired
    assert r.get_component(e, Reproductive).mate_id == mate
    repro.mate_id = None
    assert r.get_component(e, Reproductive).mate_id is None


# -- tuple defaults stay immutable ------------------------------------------


def test_diet_consumes_default_is_an_immutable_empty_tuple() -> None:
    d = Diet()
    assert isinstance(d.consumes, tuple)
    assert d.consumes == ()
    # Tuples have no append: a shared default cannot be accidentally mutated.
    with pytest.raises(AttributeError):
        d.consumes.append("grass")  # type: ignore[attr-defined]


def test_diet_consumes_per_instance_can_be_reassigned() -> None:
    r = Registry()
    e = r.create_entity(Diet(consumes=("grass", "rabbit")))
    diet = r.get_component(e, Diet)
    assert diet.consumes == ("grass", "rabbit")
    diet.consumes = ("fruit_trees",)
    assert r.get_component(e, Diet).consumes == ("fruit_trees",)


def test_two_default_diet_instances_do_not_mutate_each_other() -> None:
    a = Diet()
    b = Diet()
    # The empty tuple is a shared immutable singleton; reassigning one
    # instance's reference must not affect the other.
    a.consumes = ("shrubs",)
    assert b.consumes == ()


# -- no runtime import from the World layer ---------------------------------


def _world_import_violations(path: Path) -> list[str]:
    """Return descriptions of runtime ``world`` imports in ``path``.

    Imports guarded by ``if TYPE_CHECKING:`` are allowed (they do not execute
    at runtime). Any other ``import world`` / ``from world import ...`` /
    ``from .world import ...`` / ``population_engine.world`` reference is a
    violation: the ECS layer must stay world-free (CORE_DESIGN §8).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad: list[str] = []

    def _imports_world(node: ast.AST) -> bool:
        if isinstance(node, ast.Import):
            return any(
                n == "world"
                or n == "population_engine.world"
                or n.startswith("world.")
                or n.startswith("population_engine.world.")
                for n in (a.name for a in node.names)
            )
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if (
                mod == "world"
                or mod == "population_engine.world"
                or mod.startswith("world.")
                or mod.startswith("population_engine.world.")
            ):
                return True
            # `from . import world`
            return any(a.name == "world" for a in node.names)
        return False

    def _is_type_checking(test: ast.expr) -> bool:
        return (
            isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
        ) or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )

    def visit_body(stmts: list[ast.stmt], guarded: bool) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                if _is_type_checking(stmt.test):
                    # body runs under TYPE_CHECKING (allowed); else follows
                    visit_body(stmt.orelse, guarded)
                else:
                    visit_body(stmt.body, guarded)
                    visit_body(stmt.orelse, guarded)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if not guarded and _imports_world(stmt):
                    bad.append(f"{path.name}:{stmt.lineno}: {ast.get_source_segment(tree, stmt) or '<import>'}")
            else:
                for field in ("body", "orelse", "finalbody"):
                    seq = getattr(stmt, field, None)
                    if isinstance(seq, list):
                        visit_body(seq, guarded)

    visit_body(tree.body, guarded=False)
    return bad


def test_no_runtime_world_import_in_ecs_package() -> None:
    ecs_dir = Path(ecs_pkg.__file__).resolve().parent
    py_files = sorted(ecs_dir.glob("*.py"))
    assert py_files, "expected ecs/ python modules to scan"
    violations: list[str] = []
    for f in py_files:
        violations.extend(_world_import_violations(f))
    assert not violations, (
        "ecs/ must not import the world layer at runtime:\n" + "\n".join(violations)
    )


def test_components_module_has_no_runtime_world_import() -> None:
    # The S2 module specifically: no runtime ``world`` import (TYPE_CHECKING
    # guards would be allowed, but none are needed here).
    assert _world_import_violations(_component_module_path()) == []


def test_position_uses_plain_int_coords_not_cellcoord() -> None:
    # ``Position`` must use plain ``x: int`` / ``y: int`` — not ``world.CellCoord``.
    import typing

    hints = typing.get_type_hints(Position)
    assert hints["x"] is int, "Position.x must be int"
    assert hints["y"] is int, "Position.y must be int"
    # And ``CellCoord`` is never referenced in the components module code. The
    # docstring may mention it (as prose), so check the AST for Name/Attribute
    # references — a string docstring is a Constant, not a Name.
    tree = ast.parse(_component_module_path().read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "CellCoord":
            raise AssertionError("components.py must not reference world.CellCoord")
        if isinstance(node, ast.Attribute) and node.attr == "CellCoord":
            raise AssertionError("components.py must not reference world.CellCoord")


# -- public surface ---------------------------------------------------------


def test_core_components_and_enums_exported_from_ecs() -> None:
    import population_engine.ecs as e

    for name in (
        [c.__name__ for c in CORE_COMPONENTS]
        + [en.__name__ for en in CORE_ENUMS]
    ):
        assert hasattr(e, name), f"{name} should be exported from ecs"
        assert name in e.__all__, f"{name} should be in ecs.__all__"
