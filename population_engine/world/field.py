"""Ghost-padded numpy struct-of-arrays fields for chunk environmental state.

A :class:`Field` is one environmental quantity over one chunk, stored as a
single ghost-padded :class:`numpy.ndarray` (struct-of-arrays, SoA). The
*interior* is the real chunk data; the surrounding ring of width ``halo`` is a
read-only mirror of neighbour or world-edge values, refreshed by the owning
:class:`~population_engine.world.world.World` before each stencil pass.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["Field", "FieldSpec", "FIELD_SCHEMA", "FIELD_NAMES", "DEFAULT_HALO"]

#: Default ghost-halo width in cells (supports radius-1 stencils).
DEFAULT_HALO: int = 1


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Declarative description of one canonical environmental quantity."""

    name: str
    """Stable field identifier (e.g. ``'altitude'``). Used as the Field key."""

    dtype: np.dtype
    """numpy dtype of the backing array."""

    default: float | int
    """Value every cell (interior + halo) starts at when no data is supplied."""


#: The canonical environmental field schema, engine-wide and uniform across all
#: chunks. Order is stable and is the iteration order used by Chunk/World.
FIELD_SCHEMA: tuple[FieldSpec, ...] = (
    FieldSpec("altitude", np.dtype(np.float64), 0.0),      # metres above sea level
    FieldSpec("temperature", np.dtype(np.float64), 25.0),   # degrees Celsius
    FieldSpec("humidity", np.dtype(np.float64), 0.5),       # 0..1 relative
    FieldSpec("biome_id", np.dtype(np.int64), 0),            # 0 = unclassified
)

FIELD_NAMES: tuple[str, ...] = tuple(spec.name for spec in FIELD_SCHEMA)


class Field:
    """One environmental quantity over one chunk, as a ghost-padded ndarray.

    Layout (``chunk_size`` = S, ``halo`` = h)::

        data.shape == (S + 2*h, S + 2*h)        # row-major, row = y, col = x
        interior == data[h : h+S, h : h+S]      # the real S x S chunk cells
        halo ring == everything outside the interior

    Invariants
    ----------
    * ``data.shape == (chunk_size + 2*halo, chunk_size + 2*halo)``.
    * ``interior.shape == (chunk_size, chunk_size)`` and is a *view* of ``data``.
    * ``interior`` is the ONLY writable surface: writes through it mutate
      ``data`` in place (shared buffer) and never touch the halo.
    * ``data`` is exposed READ-ONLY (its ``writeable`` flag is False); any
      assignment through ``data`` raises ``ValueError``.
    * The halo ring is mutated ONLY by :meth:`fill_halo`. There is no other
      public writer of halo cells.
    """

    __slots__ = (
        "name",
        "_dtype",
        "chunk_size",
        "halo",
        "_data",
        "_interior",
        "_data_ro",
    )

    def __init__(
        self,
        name: str,
        dtype,
        chunk_size: int,
        halo: int = DEFAULT_HALO,
        *,
        interior: np.ndarray | None = None,
        default: float | int = 0.0,
    ) -> None:
        """Construct a ghost-padded field.

        Parameters
        ----------
        name:
            Field identifier (stable across the canonical schema).
        dtype:
            numpy dtype of the backing array and required dtype of *interior*.
        chunk_size, halo:
            Interior side length and halo width (both must be >= 1).
        interior:
            Optional S×S array of initial interior values (row-major, shape
            exactly ``(chunk_size, chunk_size)``). Copied into the buffer; the
            halo is filled with *default*. ``None`` initialises everything to
            *default*.
        default:
            Fill value for the buffer (and the pre-fill of the halo region).
        """
        if chunk_size < 1:
            raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
        if halo < 1:
            raise ValueError(f"halo must be >= 1, got {halo}")

        self.name = name
        self._dtype = np.dtype(dtype)
        self.chunk_size = chunk_size
        self.halo = halo

        size = chunk_size + 2 * halo
        # Writable buffer: interior + halo all start at `default`.
        self._data = np.full((size, size), default, dtype=self._dtype)

        if interior is not None:
            if interior.shape != (chunk_size, chunk_size):
                raise ValueError(
                    f"interior shape {tuple(interior.shape)!r} != expected "
                    f"({chunk_size}, {chunk_size})"
                )
            if np.dtype(interior.dtype) != self._dtype:
                raise ValueError(
                    f"interior dtype {np.dtype(interior.dtype)!r} != field "
                    f"dtype {self._dtype!r}"
                )
            self._data[
                halo : halo + chunk_size, halo : halo + chunk_size
            ] = interior

        # interior: the only writable surface (a view into the buffer).
        self._interior = self._data[
            halo : halo + chunk_size, halo : halo + chunk_size
        ]
        # data: read-only view of the WHOLE buffer, including the halo ring.
        # The writeable flag is per-ndarray-object, so this leaves the owner
        # buffer and the interior view writable.
        self._data_ro = self._data.view()
        self._data_ro.flags.writeable = False

    # -- accessors --------------------------------------------------------

    @property
    def dtype(self) -> np.dtype:
        """numpy dtype of the backing array."""
        return self._dtype

    @property
    def shape(self) -> tuple[int, int]:
        """Full padded shape ``((chunk_size + 2*halo,)*2)``."""
        return self._data.shape

    @property
    def interior(self) -> np.ndarray:
        """Writable ``(chunk_size, chunk_size)`` view of the real chunk cells."""
        return self._interior

    @property
    def data(self) -> np.ndarray:
        """Read-only padded view of the whole buffer, including the halo ring."""
        return self._data_ro

    # -- halo refresh -----------------------------------------------------

    def fill_halo(self, padded: np.ndarray) -> None:
        """Refresh the halo ring from a fully-resolved padded context.

        *padded* must have shape ``((chunk_size + 2*halo,)*2)`` and a dtype
        matching this field. Only the halo **ring** is copied into the backing
        buffer; the interior of *padded* is ignored and this field's interior
        is left untouched. This is the only public halo writer.

        The caller (the World) assembles *padded*: each padded cell holds the
        value of the real world cell at the corresponding (clamped) world
        coordinate, where world-edge coordinates clamp to the world boundary
        (reflective / zero-gradient).
        """
        if padded.shape != self._data.shape:
            raise ValueError(
                f"padded shape {tuple(padded.shape)!r} != field shape "
                f"{self._data.shape!r}"
            )
        if np.dtype(padded.dtype) != self._dtype:
            raise ValueError(
                f"padded dtype {np.dtype(padded.dtype)!r} != field dtype "
                f"{self._dtype!r}"
            )
        h = self.halo
        # Copy the four edge strips into the writable buffer. The four
        # assignments overlap at the corners; values there are mutually
        # consistent by construction (padded is one fully-resolved array), so
        # last-write-wins leaves the correct value. The interior region
        # [h:h+S, h:h+S] is never assigned, so it is untouched.
        self._data[:h, :] = padded[:h, :]
        self._data[-h:, :] = padded[-h:, :]
        self._data[:, :h] = padded[:, :h]
        self._data[:, -h:] = padded[:, -h:]
