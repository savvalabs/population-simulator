"""Entity-Component-System: archetype storage, queries, scheduler, and events."""

from .component import Component
from .enums import AgeStage, DietType, MovementState, Sex
from .entity import Entity, EntityAllocator
from .archetype import Archetype
from .query import Query
from .registry import Registry
from .components import (
    Age,
    CellExposure,
    Diet,
    MovementLog,
    Position,
    Reproductive,
    SpeciesRef,
    Vitals,
)
from .events import Event, EventBus, Subscription
from .scheduler import Scheduler, System, SystemContext

from .errors import (  # noqa: F401 — explicit re-export by name
    ComponentError,
    EcsError,
    EventError,
    InvalidEntityError,
    SchedulerError,
)

__all__ = [
    "Age",
    "AgeStage",
    "Archetype",
    "CellExposure",
    "Component",
    "ComponentError",
    "Diet",
    "DietType",
    "EcsError",
    "Entity",
    "EntityAllocator",
    "Event",
    "EventBus",
    "EventError",
    "InvalidEntityError",
    "MovementLog",
    "MovementState",
    "Position",
    "Query",
    "Registry",
    "Reproductive",
    "Scheduler",
    "SchedulerError",
    "Sex",
    "SpeciesRef",
    "Subscription",
    "System",
    "SystemContext",
    "Vitals",
]