"""Entity-Component-System: archetype storage, queries, scheduler, and events."""

from .component import Component
from .entity import Entity, EntityAllocator
from .archetype import Archetype
from .query import Query
from .registry import Registry
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
    "Archetype",
    "Component",
    "ComponentError",
    "EcsError",
    "Entity",
    "EntityAllocator",
    "Event",
    "EventBus",
    "EventError",
    "InvalidEntityError",
    "Query",
    "Registry",
    "Scheduler",
    "SchedulerError",
    "Subscription",
    "System",
    "SystemContext",
]