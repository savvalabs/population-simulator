"""Exception types raised by the ECS subpackage.

All ECS errors derive from :class:`EcsError` so callers can catch the family
broadly while still distinguishing specific failure modes.
"""

from __future__ import annotations

__all__ = [
    "EcsError",
    "InvalidEntityError",
    "ComponentError",
    "SchedulerError",
    "EventError",
]


class EcsError(Exception):
    """Base class for all ECS errors."""


class InvalidEntityError(EcsError):
    """An operation was attempted on a destroyed or recycled entity handle."""


class ComponentError(EcsError):
    """Invalid component registration or component operation."""


class SchedulerError(EcsError):
    """Invalid system graph: cycles, unknown deps, duplicate names, bad access."""


class EventError(EcsError):
    """Invalid event-bus usage (e.g. cancelling a subscription twice)."""
