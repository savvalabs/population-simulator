"""Tests for :mod:`population_engine.ecs.scheduler`."""

from __future__ import annotations

import pytest

from population_engine.ecs.errors import SchedulerError
from population_engine.ecs.events import EventBus
from population_engine.ecs.registry import Registry
from population_engine.ecs import scheduler as _mod
from population_engine.ecs.scheduler import Scheduler, System, SystemContext

from ._components import Health, Position, Tag, Velocity

# -- trivial helpers (not real systems, just order-tracking stubs) ----------


def _sys(name: str, reads=(), writes=(), after=()) -> type[System]:
    """Return a System subclass with the given declarations."""
    attrs: dict = {
        "name": name,
        "reads": reads,
        "writes": writes,
        "after": after,
        "update": lambda self, ctx: self._recorder.append(self.name),
    }
    return type(name, (System,), attrs)


def _make(name: str, reads=(), writes=(), after=()) -> System:
    """Instantiate a stub system with an internal recorder list."""
    cls = _sys(name, reads, writes, after)
    instance = cls()
    instance._recorder = []  # type: ignore[attr-defined]
    return instance


def _collect_order(systems: list[System]) -> list[str]:
    """Build, execute against empty context, and return the recorder state."""
    ctx = SystemContext(registry=Registry(), events=EventBus())
    sched = Scheduler()
    for s in systems:
        sched.add_system(s)
    # Clear stale entries from any prior run with the same system instances.
    for s in systems:
        s._recorder.clear()  # type: ignore[attr-defined]
    sched.execute(ctx)
    # Read back in execution order (not argument order), so `after` effects
    # are visible.
    result: list[str] = []
    for s in sched.order():
        result.extend(s._recorder)  # type: ignore[attr-defined]
    return result


# -- registration-order determinism -----------------------------------------


def test_registration_order_preserved_when_no_constraints() -> None:
    a, b, c = _make("a"), _make("b"), _make("c")
    assert _collect_order([a, b, c]) == ["a", "b", "c"]


def test_after_alone_reorders_without_affecting_unrelated() -> None:
    a = _make("a")
    b = _make("b", after=("a",))
    c = _make("c")
    # b must run after a; c stays first (reg idx 0, indeg 0).
    # Kahn pops by heap (reg idx) — c and a are indeg 0, c pops first.
    assert _collect_order([a, b, c]) == ["a", "b", "c"]
    # Reverse registration: c, b, a. c(idx 0) pops first, then a(idx 2).
    assert _collect_order([c, b, a]) == ["c", "a", "b"]
    # a still precedes b — the dep is satisfied.


def test_chain_of_after_is_respected() -> None:
    a = _make("a")
    b = _make("b", after=("a",))
    c = _make("c", after=("b",))
    d = _make("d")
    # Registration [d, c, b, a]. d(idx 0) and a(idx 3) indeg 0.
    # Heap pops d first (lower idx), then a, then b, then c.
    assert _collect_order([d, c, b, a]) == ["d", "a", "b", "c"]
    # Chain a→b→c is preserved.


# -- stages (conflict-based parallelism grouping) ---------------------------


def test_write_read_conflict_splits_stages() -> None:
    a = _make("A", writes=(Position,))
    b = _make("B", reads=(Position,))
    sched = Scheduler()
    sched.add_system(a)
    sched.add_system(b)
    stages = sched.stages()
    assert len(stages) == 2
    # A (writer) before B (reader). They are in distinct stages.
    assert stages[0] == (a,)
    assert stages[1] == (b,)


def test_write_write_conflict_splits_stages() -> None:
    a = _make("A", writes=(Position,))
    b = _make("B", writes=(Position,))
    sched = Scheduler()
    sched.add_system(a)
    sched.add_system(b)
    stages = sched.stages()
    assert len(stages) == 2
    # registration order resolves the tie.
    assert stages[0] == (a,)
    assert stages[1] == (b,)


def test_read_read_is_not_a_conflict() -> None:
    a = _make("A", reads=(Position,))
    b = _make("B", reads=(Position,))
    sched = Scheduler()
    sched.add_system(a)
    sched.add_system(b)
    assert len(sched.stages()) == 1  # both can run together (same stage).


def test_disjoint_access_same_stage() -> None:
    a = _make("A", writes=(Position,))
    b = _make("B", writes=(Velocity,))  # no overlap with Position
    sched = Scheduler()
    sched.add_system(a)
    sched.add_system(b)
    assert len(sched.stages()) == 1


def test_multiple_systems_in_two_stages() -> None:
    # A(writes P), B(reads P), C(reads V), D(writes V).
    # Conflicts: A-B (write/read P), C-D (read/write V). No other shared.
    # Conflict edges directed along T (registration order): A→B, C→D.
    # Levels: A=0, B=1, C=0, D=1. So stages: 0=[A,C], 1=[B,D].
    a = _make("A", writes=(Position,))
    b = _make("B", reads=(Position,))
    c = _make("C", reads=(Velocity,))
    d = _make("D", writes=(Velocity,))
    sched = Scheduler()
    for s in (a, b, c, d):
        sched.add_system(s)
    stages = sched.stages()
    assert len(stages) == 2
    assert set(s.name for s in stages[0]) == {"A", "C"}
    assert set(s.name for s in stages[1]) == {"B", "D"}
    # Within stage, order must match registration: A,C and B,D.
    assert [s.name for s in stages[0]] == ["A", "C"]
    assert [s.name for s in stages[1]] == ["B", "D"]


# -- execution --------------------------------------------------------------


def test_execute_calls_update_in_order() -> None:
    ctx = SystemContext(registry=Registry(), events=EventBus())
    sched = Scheduler()
    a = _make("a")
    b = _make("b", after=("a",))
    sched.add_system(a)
    sched.add_system(b)
    sched.execute(ctx)
    assert a._recorder + b._recorder == ["a", "b"]  # type: ignore[attr-defined]


def test_execute_is_idempotent_and_reproducible() -> None:
    ctx = SystemContext(registry=Registry(), events=EventBus())
    sched = Scheduler()
    a, b, c = _make("a"), _make("b"), _make("c")
    for s in (a, b, c):
        sched.add_system(s)
    sched.execute(ctx)
    first = [s._recorder[:] for s in (a, b, c)]  # type: ignore[attr-defined]
    # Clear recorders and run again — same order.
    for s in (a, b, c):
        s._recorder.clear()  # type: ignore[attr-defined]
    sched.execute(ctx)
    second = [s._recorder[:] for s in (a, b, c)]  # type: ignore[attr-defined]
    assert first == second


def test_context_carries_registry_and_events() -> None:
    reg = Registry()
    ev = EventBus()
    ctx = SystemContext(registry=reg, events=ev)
    assert ctx.registry is reg and ctx.events is ev


def test_context_is_frozen() -> None:
    ctx  = SystemContext(registry=Registry(), events=EventBus())
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        ctx.registry = Registry()  # type: ignore[misc]


# -- error cases ------------------------------------------------------------


def test_cycle_in_explicit_deps_raises() -> None:
    sched = Scheduler()
    a = _make("a", after=("b",))
    b = _make("b", after=("a",))
    sched.add_system(a)
    sched.add_system(b)
    with pytest.raises(SchedulerError, match="cycle"):
        sched.build()


def test_unknown_after_target_raises() -> None:
    sched = Scheduler()
    sched.add_system(_make("a", after=("no_such_system",)))
    with pytest.raises(SchedulerError, match="unknown"):
        sched.build()


def test_duplicate_name_raises() -> None:
    sched = Scheduler()
    sched.add_system(_make("dup"))
    with pytest.raises(SchedulerError, match="duplicate"):
        sched.add_system(_make("dup"))


def test_empty_name_raises() -> None:
    with pytest.raises(SchedulerError, match="no name"):
        Scheduler().add_system(_make(""))


def test_non_component_in_access_raises() -> None:
    with pytest.raises(SchedulerError, match="reads"):
        Scheduler().add_system(_make("bad", reads=(int,)))
    with pytest.raises(SchedulerError, match="writes"):
        Scheduler().add_system(_make("bad", writes=(str,)))


def test_non_class_in_access_raises() -> None:
    with pytest.raises(SchedulerError, match="reads"):
        Scheduler().add_system(_make("bad", reads=("not-a-class",)))  # type: ignore[arg-type]


def test_bogus_after_entry_raises() -> None:
    with pytest.raises(SchedulerError, match="after"):
        Scheduler().add_system(_make("a", after=("",)))


def test_order_and_stages_work_before_explicit_build() -> None:
    sched = Scheduler()
    a, b = _make("a"), _make("b", after=("a",))
    sched.add_system(a)
    sched.add_system(b)
    # Implicit build on first use.
    order = sched.order()
    assert order == (a, b)
    # stages also auto-build.
    assert len(sched.stages()) == 2


def test_add_system_rejects_non_system() -> None:
    with pytest.raises(TypeError):
        Scheduler().add_system(object())  # type: ignore[arg-type]