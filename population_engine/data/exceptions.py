"""Exception types raised by the data subpackage.

All data-layer errors derive from :class:`DataRegistryError` so callers can
catch the family broadly while still distinguishing specific failure modes —
duplicate ids on load, unknown ids on lookup, and malformed/invalid records on
construction or conversion.

The data layer is pure value objects + loaders + a registry; it owns no
behaviour and reads no world/ECS/time state, so these four exceptions are the
complete failure surface of the subsystem.
"""

from __future__ import annotations

__all__ = [
    "DataRegistryError",
    "DuplicateDataError",
    "UnknownDataError",
    "InvalidDataError",
]


class DataRegistryError(Exception):
    """Base class for all data-subsystem errors."""


class DuplicateDataError(DataRegistryError):
    """An id was loaded more than once (intra-batch or vs already-loaded)."""


class UnknownDataError(DataRegistryError):
    """A lookup requested an id that is not present in the registry."""


class InvalidDataError(DataRegistryError):
    """A record or model instance failed validation (shape, range, type)."""
