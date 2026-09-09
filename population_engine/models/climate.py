"""The climate equation: provisional deterministic driver of the climate Fields.

This is the ``models/``-layer half of S3.1 (CORE_DESIGN §9): the pure equation
that maps already-resolved per-cell base climate values (``base_temperature`` /
``base_humidity`` / ``base_precipitation``) plus ``altitude``, the season label
and the RNG into the refreshed ``temperature`` / ``humidity`` /
``precipitation`` arrays.

Layer contract (CORE_DESIGN §1.2, §8): this module imports NOTHING from
``world``, ``ecs``, ``core``, the RNG/time singletons, or the ``data``
loaders. The season label is a plain ``str``; the RNG is passed in; the base
climate values are *already-resolved* per-cell arrays supplied by the caller
(the ``ClimateSystem`` integrator, via the D1 biome-provider seam). The model
is therefore fully unit-testable with synthetic arrays and no engine, no world,
and no registry. It performs no I/O, holds no state, and touches no ``Field``.

# --------------------------------------------------------------------------- #
# PROVISIONAL EQUATIONS — D2-D5 are intentionally UNRESOLVED in CORE_DESIGN.   #
# --------------------------------------------------------------------------- #
#
# CORE_DESIGN §3.1 / §5.2 / §9 require ClimateSystem to drive the climate
# Fields "from biome + season + altitude + RNG noise", but give NO equation:
#
#   - D2 (altitude dependence) — which quantities depend on altitude, and the
#     functional form, are unspecified. §9 names only "altitudinal lapse".
#   - D3 (seasonal dependence) — only that seasons are discrete labels (no
#     continuous day-of-year curve) is fixed; magnitudes are unauthored.
#   - D4 (RNG noise) — the form and magnitudes (sigma) are unspecified.
#   - D5 (clamping / bounds) — unspecified (beyond §6's humidity = 0..1).
#
# Per the S3 directive, the gap is NOT solved here. Every equation below is the
# *simplest deterministic* placeholder that satisfies the stated dependencies
# (discrete seasons, altitude dependence, RNG noise) while keeping every
# assumption isolated in :class:`ClimateParams` and replaceable without
# touching the integrator. Each placeholder carries a ``TODO(climate/Dx)``
# marker referencing CORE_DESIGN. When D2-D5 are decided, replace this module;
# :class:`~population_engine.systems.climate.ClimateSystem` is unchanged, and
# :mod:`population_engine.models.climate` imports flow through unchanged names.

D1 (per-cell biome acquisition) is a *separate* open question, deferred behind
the biome-provider seam in the integrator; see
``docs/open-questions/D1-biome-acquisition.md``. This model never sees it: it
receives already-resolved base values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = ["ClimateParams", "ClimateModel"]


@dataclass(frozen=True, slots=True)
class ClimateParams:
    """ALL provisional climate constants, in ONE place.

    Every value here is a documented *provisional assumption*; CORE_DESIGN
    gives none of them (D2-D5 open). Replacing this object replaces the
    climate model's tuning surface without touching the equation shape or the
    integrator (:class:`ClimateSystem`). Each block below carries the
    ``TODO(climate/Dx)`` marker for the open design question it provisionalises.
    """

    # -- D2: altitude dependence --------------------------------------------
    # Provisional: ONLY temperature uses altitude, via a linear environmental
    # lapse rate Gamma (deg C of cooling per metre of altitude). Gamma = 0.0065
    # is the standard-atmosphere lapse rate -- a real physical constant reused
    # here, NOT inherited from World generation. ``base_temperature`` is
    # treated as the sea-level-equivalent reference for the biome; the lapse
    # term adjusts it to the cell's actual altitude.
    # TODO(climate/D2): form & scope of altitude dependence unspecified by
    # CORE_DESIGN §3.1 / §9 ("altitudinal lapse" names the dependency only).
    temperature_lapse_c_per_m: float = 0.0065

    # -- D3: discrete-season dependence -------------------------------------
    # Provisional additive offsets / multiplicative scales keyed by season
    # label (opaque ``str`` from ``core.time.SeasonCalendar``; the bundled
    # tropical calendar uses ``"dry"`` / ``"rainy"``). Magnitudes are authored
    # HERE -- NOT in BiomeData (no per-season amplitude is authored) -- and are
    # documented placeholders. An unknown season label falls back to a neutral
    # default (0.0 additive / 1.0 multiplicative) so a custom calendar does not
    # crash the model; that fallback is itself a provisional assumption.
    # TODO(climate/D3): CORE_DESIGN fixes only discrete labels; magnitudes are
    # unauthored. Replace when a season model is decided.
    season_temperature_offset_c: Mapping[str, float] = field(
        default_factory=lambda: {"dry": 0.0, "rainy": -2.0}
    )
    season_humidity_delta: Mapping[str, float] = field(
        default_factory=lambda: {"dry": 0.0, "rainy": 0.1}
    )
    season_precipitation_multiplier: Mapping[str, float] = field(
        default_factory=lambda: {"dry": 0.5, "rainy": 1.5}
    )

    # -- D4: RNG noise ------------------------------------------------------
    # Provisional zero-mean additive Gaussian noise, one independent draw per
    # cell per quantity (shape taken from the altitude array). Consumes the
    # shared RNG in a fixed call order (temperature, then humidity, then
    # precipitation) so the model is deterministic given one shared generator.
    # sigma values are documented placeholders.
    # TODO(climate/D4): form & magnitudes of noise unspecified by CORE_DESIGN.
    temperature_noise_sigma: float = 1.0
    humidity_noise_sigma: float = 0.05
    precipitation_noise_sigma: float = 0.05

    # -- D5: clamping / bounds ----------------------------------------------
    # Humidity is a relative fraction in [0, 1] (CORE_DESIGN §6) -> clamped.
    # Precipitation is a non-negative rate -> floored at 0. Temperature is left
    # UNclamped provisionally (D5 open); a physical floor/ceiling can be added
    # when bounds are decided.
    # TODO(climate/D5): bounds unspecified by CORE_DESIGN beyond §6 humidity.
    humidity_min: float = 0.0
    humidity_max: float = 1.0
    precipitation_floor: float = 0.0

    # NB: the per-season lookup + neutral fallback (unknown season -> 0.0
    # additive, 1.0 multiplicative) is applied in
    # :meth:`ClimateModel.step` directly against the tables above. There are NO
    # accessor methods shadowing a table field here -- a stored field and a
    # method cannot share a name on a dataclass, so the lookup lives in
    # ``step`` (CORE_DESIGN §3.1; provisional assumption, D3 open).


@dataclass(frozen=True, slots=True)
class ClimateModel:
    """The provisional climate equation (CORE_DESIGN §9; D2-D5 open).

    Bundles :class:`ClimateParams` (every constant, one place) with the pure
    equation. The equation is a deterministic function of its explicit inputs
    and holds no state; it performs no I/O and touches no ``Field`` / world.
    The integrator (:class:`~population_engine.systems.climate.ClimateSystem`)
    owns the world/data wiring and calls :meth:`step` with already-resolved
    arrays, so swapping the model or its params never touches the integrator.
    """

    params: ClimateParams = field(default_factory=ClimateParams)

    def step(
        self,
        *,
        altitude: "NDArray[np.floating]",
        base_temperature: "NDArray[np.floating]",
        base_humidity: "NDArray[np.floating]",
        base_precipitation: "NDArray[np.floating]",
        season: str,
        rng: np.random.Generator,
    ) -> tuple["NDArray[np.floating]", "NDArray[np.floating]", "NDArray[np.floating]"]:
        """Return refreshed ``(temperature, humidity, precipitation)`` arrays.

        All four array inputs are per-cell and share one shape; ``altitude`` is
        metres, ``base_*`` are already-resolved biome base values, ``season`` is
        an opaque label, ``rng`` is the shared deterministic generator. Outputs
        are new (never aliased to inputs), ``float64``. Equations are provisional
        -- see the module docstring and the per-line ``TODO(climate/Dx)`` markers.
        """
        p = self.params
        shape = altitude.shape
        # Season terms: per-season table lookup with a NEUTRAL fallback so an
        # unknown season label (a custom calendar) never crashes the model.
        # Provisional assumption (D3 open): neutral == no shift -- 0.0 additive
        # for temperature/humidity, 1.0 multiplicative for precipitation.
        # TODO(climate/D3): CORE_DESIGN §3.1/§5.2/§9 fix only discrete labels;
        # magnitudes + the fallback policy are unauthored here.
        t_off = p.season_temperature_offset_c.get(season, 0.0)
        h_del = p.season_humidity_delta.get(season, 0.0)
        p_mul = p.season_precipitation_multiplier.get(season, 1.0)

        # Temperature: base - lapse*altitude + season offset + noise.
        # TODO(climate/D2/D3/D4): provisional linear lapse + additive season
        # offset + zero-mean Gaussian noise; CORE_DESIGN §3.1/§5.2/§9 name the
        # dependencies only, no equation.
        temperature = (
            base_temperature
            - p.temperature_lapse_c_per_m * altitude
            + t_off
            + rng.normal(0.0, p.temperature_noise_sigma, size=shape)
        )

        # Humidity: base + season delta + noise, clamped to [0, 1] (§6).
        # TODO(climate/D3/D4/D5): provisional additive season + Gaussian noise
        # + §6-grounded clamp. No altitude term (D2 provisional: lapse is
        # temperature-only).
        humidity = np.clip(
            base_humidity + h_del + rng.normal(0.0, p.humidity_noise_sigma, size=shape),
            p.humidity_min,
            p.humidity_max,
        )

        # Precipitation: base * season multiplier + noise, floored at 0.
        # TODO(climate/D3/D4/D5): provisional multiplicative season multiplicative
        # + Gaussian noise + non-negative floor. No altitude term.
        precipitation = np.maximum(
            base_precipitation * p_mul
            + rng.normal(0.0, p.precipitation_noise_sigma, size=shape),
            p.precipitation_floor,
        )

        # Pin the climate-Field dtype contract (float64) regardless of the
        # provider's input dtype; ``copy=False`` is a no-op when already float64
        # so the common path allocates nothing extra.
        return (
            temperature.astype(np.float64, copy=False),
            humidity.astype(np.float64, copy=False),
            precipitation.astype(np.float64, copy=False),
        )
