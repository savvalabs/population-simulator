"""System scheduling.

Systems implement one slice of simulation behaviour (AI, metabolism, climate,
...). Each system declares which component types it :attr:`reads` and
:writes`, and the systems it must run :attr:`after`. The :class:`Scheduler`
builds a deterministic execution order from those declarations and computes
conflict-free *stages*: systems in the same stage have no dependency between
them (no explicit ordering, and their declared component access does not
conflict), so a future parallel executor could run a single stage's systems
concurrently. Today the scheduler executes stages sequentially, within each
stage by a stable registration-derived order, which is fully deterministic and
reproducible given the same set of systems added in the same order.

**Ordering rules**
* Explicit ``after`` dependencies are honoured.
* Otherwise registration order is preserved (stable tiebreak).
* Two systems that *conflict* (a shared component with a writer among them) are
  placed in different stages — they can never run concurrently.
* Read / read on shared components is *not* a conflict, so those systems can
  co-reside in a stage.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .component import Component
from .errors import SchedulerError

if TYPE_CHECKING:
    from .events import EventBus
    from .registry import Registry

__all__ = ["System", "SystemContext", "Scheduler"]


@dataclass(frozen=True, slots=True)
class SystemContext:
    """Shared engine state passed to each system on :meth:`System.update`.

    In the ECS foundation slice this holds the :class:`Registry` and
    :class:`EventBus`. When the engine integration subsystem lands it will be
    extended with the simulation clock and the engine's deterministic RNG, so
    systems can consume them without signature churn.
    """

    registry: "Registry"
    events: "EventBus"


class System:
    """Base class for ECS systems. Subclass and implement :meth:`update`.

    **Class attributes** (set on the subclass body):

    ``name``
        Unique system identifier (non-empty string). Required.
    ``reads``
        Component types the system reads but does not write (tuple of classes).
    ``writes``
        Component types the system writes (tuple of classes).
    ``after``
        Names of systems this one must execute *after* (tuple of strings).
        References a system that has not been added to the scheduler is an error
        at build time.
    """

    name: str = ""
    reads: tuple = ()   # tuple[type[Component], ...]
    writes: tuple = ()  # tuple[type[Component], ...]
    after: tuple = ()   # tuple[str, ...]

    def update(self, ctx: SystemContext) -> None:
        """Implement the per-tick work of this system."""
        raise NotImplementedError(
            f"system {type(self).__name__!r} must implement update(ctx)"
        )


class Scheduler:
    """Deterministic, stage-aware system executor.

    Feed systems via :meth:`add_system` in registration order, then call
    :meth:`execute` each tick. The first :meth:`execute` (or an explicit
    :meth:`build`) computes and caches the schedule.
    """

    __slots__ = ("_systems", "_by_name", "_built", "_order", "_stages")

    def __init__(self) -> None:
        self._systems: list[System] = []
        self._by_name: dict[str, System] = {}
        self._built = False
        self._order: list[System] = []               # total deterministic order
        self._stages: list[list[System]] = []         # each stage = parallel-safe batch

    # -- registration ---------------------------------------------------

    def add_system(self, system: System) -> None:
        if not isinstance(system, System):
            raise TypeError(f"expected a System, got {system!r}")
        name = system.name
        if not name:
            raise SchedulerError(
                f"system {type(system).__name__!r} has no name (must be a non-empty string)"
            )
        if name in self._by_name:
            raise SchedulerError(f"duplicate system name {name!r}")
        self._validate_access(system.reads, system, "reads")
        self._validate_access(system.writes, system, "writes")
        for dep in system.after:
            if not isinstance(dep, str) or not dep:
                raise SchedulerError(
                    f"invalid after-entry in {name!r}: {dep!r} "
                    "(must be a non-empty system name)"
                )
        self._systems.append(system)
        self._by_name[name] = system
        self._built = False

    # -- build ----------------------------------------------------------

    def build(self) -> None:
        n = len(self._systems)
        # name -> registration index
        idx = {s.name: i for i, s in enumerate(self._systems)}
        for s in self._systems:
            for dep in s.after:
                if dep not in idx:
                    raise SchedulerError(
                        f"system {s.name!r} depends on unknown system {dep!r}"
                    )

        # 1. Explicit-dependency-only adj; topo-sort with reg-index tiebreak → T.
        explicit_adj: list[set[int]] = [set() for _ in range(n)]
        indeg = [0] * n
        for s in self._systems:
            j = idx[s.name]
            for dep in s.after:
                i = idx[dep]
                if j not in explicit_adj[i]:
                    explicit_adj[i].add(j)
                    indeg[j] += 1
        order_idx = _kahn(explicit_adj, indeg, n)
        # T_pos: position of each system in the explicit-only total order.
        tpos: list[int] = [-1] * n
        for pos, i in enumerate(order_idx):
            tpos[i] = pos

        # 2. Full graph = explicit + conflict edges (directed along T so acyclic).
        full_adj: list[set[int]] = [set(explicit_adj[i]) for i in range(n)]
        for a in range(n):
            for b in range(a + 1, n):
                if not _conflict(self._systems[a], self._systems[b]):
                    continue
                # Direct the edge from the system that comes first in T to the
                # one that comes later, so the edge is always forward in T.
                u, v = (a, b) if tpos[a] < tpos[b] else (b, a)
                full_adj[u].add(v)

        # 3. Longest-path levels on the full DAG (relax along T order).
        level = [0] * n
        for i in order_idx:
            base = level[i]
            for j in full_adj[i]:
                if level[j] < base + 1:
                    level[j] = base + 1

        max_level = max(level) if n else -1
        stages_list: list[list[System]] = [[] for _ in range(max_level + 1)]
        for i in order_idx:
            stages_list[level[i]].append(self._systems[i])

        self._order = [self._systems[i] for i in order_idx]
        self._stages = stages_list
        self._built = True

    # -- execution -----------------------------------------------------

    def execute(self, ctx: SystemContext) -> None:
        """Run every system in dependency order (stage by stage)."""
        self._ensure_built()
        for stage in self._stages:
            for system in stage:
                system.update(ctx)

    # -- inspection (for tests / diagnostics) --------------------------

    def order(self) -> tuple[System, ...]:
        """The total deterministic execution order."""
        self._ensure_built()
        return tuple(self._order)

    def stages(self) -> tuple[tuple[System, ...], ...]:
        """Stage groups; within each stage systems are safe to parallelise.
        """
        self._ensure_built()
        return tuple(tuple(s) for s in self._stages)

    # -- internals ----------------------------------------------------

    def _ensure_built(self) -> None:
        if not self._built:
            self.build()

    @staticmethod
    def _validate_access(types: tuple, system: System, label: str) -> None:
        for t in types:
            if not isinstance(t, type):
                raise SchedulerError(
                    f"{label} of system {system.name!r} contains "
                    f"a non-class entry {t!r}"
                )
            if not issubclass(t, Component):
                raise SchedulerError(
                    f"{label} of system {system.name!r} contains "
                    f"{t!r} which is not a Component subclass"
                )


# -- free functions (module-scope stateless helpers) -------------------------


def _conflict(a: System, b: System) -> bool:
    """True when two systems share a component and at least one writes it."""
    a_write = set(a.writes)
    a_read = set(a.reads)
    b_write = set(b.writes)
    b_read = set(b.reads)
    shared = (a_write | a_read) & (b_write | b_read)
    for c in shared:
        if c in a_write or c in b_write:
            return True
    return False


def _kahn(adj: list[set[int]], indeg: list[int], n: int) -> list[int]:
    """Kahn's topological sort with registration-index tiebreak heap."""
    heap = [i for i in range(n) if indeg[i] == 0]
    heapq.heapify(heap)
    out: list[int] = []
    local = indeg[:]
    while heap:
        i = heapq.heappop(heap)
        out.append(i)
        for j in sorted(adj[i]):
            local[j] -= 1
            if local[j] == 0:
                heapq.heappush(heap, j)
    if len(out) != n:
        raise SchedulerError(
            "cycle detected in explicit system dependencies (after)"
        )
    return out