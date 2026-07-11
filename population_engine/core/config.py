"""Engine configuration.

A single immutable ``EngineConfig`` carries the engine-level knobs that every
subsystem needs: the deterministic seed, the simulation time scale (ticks per
day), the tick budget, and the playback-speed envelope.

Configuration is deliberately *engine-level*: world dimensions, biome sets, and
species parameters belong to the ``world`` and ``data`` subsystems and are not
modelled here. Core establishes only the determinism and time-scale contract the
rest of the engine is built on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["EngineConfig"]


@dataclass(frozen=True)
class EngineConfig:
    """Immutable engine-level configuration.

    Attributes
    ----------
    seed:
        Seed for the engine's deterministic random generator. Two engines
        created with the same seed produce identical random streams and thus
        identical simulations (given the same systems/input).
    ticks_per_day:
        Number of simulation ticks that make one in-world day. Must be >= 1.
        Drives the calendar in :mod:`population_engine.core.time`.
    start_tick:
        Absolute tick index the simulation begins at. Defaults to 0.
    max_ticks:
        Optional hard ceiling on executed ticks. When ``ticks_executed`` reaches
        this value the engine auto-stops. ``None`` means unbounded.
    default_speed / min_speed / max_speed:
        Playback-speed envelope, in simulation ticks per wall-clock second. This
        is a *control hint* for a real-time driver (e.g. the API layer); the
        synchronous :meth:`Engine.tick` / :meth:`Engine.run` never block on it.
    """

    seed: int = 0
    ticks_per_day: int = 24
    start_tick: int = 0
    max_ticks: int | None = None
    default_speed: float = 1.0
    min_speed: float = 0.0
    max_speed: float = 100.0

    def __post_init__(self) -> None:
        if self.ticks_per_day < 1:
            raise ValueError(
                f"ticks_per_day must be >= 1, got {self.ticks_per_day!r}"
            )
        if self.start_tick < 0:
            raise ValueError(
                f"start_tick must be >= 0, got {self.start_tick!r}"
            )
        if self.max_ticks is not None and self.max_ticks < 0:
            raise ValueError(
                f"max_ticks must be >= 0 or None, got {self.max_ticks!r}"
            )
        if self.min_speed < 0.0:
            raise ValueError(
                f"min_speed must be >= 0, got {self.min_speed!r}"
            )
        if self.min_speed > self.max_speed:
            raise ValueError(
                f"min_speed ({self.min_speed}) must be <= "
                f"max_speed ({self.max_speed})"
            )
        if not (self.min_speed <= self.default_speed <= self.max_speed):
            raise ValueError(
                f"default_speed ({self.default_speed}) must be within "
                f"[min_speed ({self.min_speed}), max_speed ({self.max_speed})]"
            )

    def rng(self) -> np.random.Generator:
        """Return a fresh deterministic NumPy generator seeded from ``seed``.

        Each call returns an independent generator initialised from the same
        seed, so two configs with the same seed produce identical streams.
        """
        return np.random.default_rng(self.seed)
