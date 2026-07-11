"""Shared sample components for ECS tests."""

from __future__ import annotations

from dataclasses import dataclass

from population_engine.ecs import Component


@dataclass
class Position(Component):
    x: int = 0
    y: int = 0


@dataclass
class Velocity(Component):
    vx: int = 0
    vy: int = 0


@dataclass
class Health(Component):
    hp: int = 100


@dataclass
class Tag(Component):
    name: str = ""
