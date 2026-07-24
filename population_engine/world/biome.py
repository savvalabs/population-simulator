"""Biome definitions for terrain classification.

Biomes are declarative parameter-range templates. During procedural generation,
each cell's altitude, temperature, and humidity are matched against the biome
table to assign a ``biome_id``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Biome"]


@dataclass(frozen=True, slots=True)
class Biome:
    """Declarative specification of a biome type.

    Ranges are inclusive on min, exclusive on max (``min <= value < max``).
    The first matching biome in the table wins, so order biomes from most
    specific to most general.
    """

    name: str
    """Human-readable label (e.g. 'páramo', 'cloud-forest', 'dry-scrub')."""

    min_altitude: float = 0.0
    max_altitude: float = 6000.0

    min_temperature: float = -20.0
    max_temperature: float = 50.0

    min_humidity: float = 0.0
    max_humidity: float = 1.0

    def matches(self, altitude: float, temperature: float, humidity: float) -> bool:
        """True when the given values fall within all ranges of this biome."""
        return (
            self.min_altitude <= altitude < self.max_altitude
            and self.min_temperature <= temperature < self.max_temperature
            and self.min_humidity <= humidity < self.max_humidity
        )