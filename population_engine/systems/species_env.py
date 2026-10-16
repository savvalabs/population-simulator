"""SpeciesEnvSystem: per-species environment configuration (S3 add-on).

The mockup's global "Variables de Entorno" panel becomes a per-species
configuration so each animal feels the world differently:

* ``food`` (0-10, solo herbívoros): bonus/penalti de energía — las presas
  comen mejor o peor; los carnívoros (tigrillo, águila) no tienen esta
  palanca: su comida son los ñeques.
* ``space`` (0-10): hábitat — si está bajo, las entidades de esa especie se
  ven empujadas hacia el centro del mapa (el hábitat se encoge) sin morir:
  NO afecta a ninguna otra especie (el ñeque es presa; no puede influir en
  la cadena a través de su slider de espacio).
* ``contamination`` (0-10): drenaje per-capita para esa especie.
* ``disease`` (0-10): drenaje crónico por enfermedad específica.

Sin RNG: efectos puramente deterministas en el orden de los arquetipos.
Configurable en caliente vía ``set_config`` / ``get_config``.
"""

from __future__ import annotations

from ..ecs.components import Diet, EnergyComponent, Position, SpeciesRef
from ..ecs.enums import DietType
from ..ecs.scheduler import System, SystemContext

__all__ = ["SpeciesEnvSystem"]

# Escalas de efecto por punto de slider.
FOOD_BONUS: float = 0.5    # por punto por encima de 5 (abundancia)
FOOD_STARVE: int = 5       # por punto por debajo de 5 (hambre real)
SPACE_INSET: int = 6       # celdas de margen por punto de espacio faltante
CONTAM_DRAIN: float = 1.5    # por punto de contaminación (fue 0.3 — trivial)
DISEASE_DRAIN: float = 2.5   # por punto de enfermedad (fue 0.4 — nunca ganaba al forrajeo)
SPACE_RING: int = 1        # celdas de anillo por punto de falta de espacio


class SpeciesEnvSystem(System):
    """Applies per-species environment sliders to that species's energy."""

    name = "species_env"
    reads: tuple = (SpeciesRef, Diet, Position, EnergyComponent)
    writes: tuple = (EnergyComponent, Position)
    # Después del estrés ambiental genérico y antes de la muerte.
    after: tuple = ("environment_pressure",)

    def __init__(self, world_size: int = 128) -> None:
        self.world_size = int(world_size)
        # config: species_id -> {"food":int, "space":int, "contamination":int,
        #                        "disease":int}
        # Valores por defecto sanos: ninguna presión.
        self._config: dict[str, dict[str, int]] = {
            "neque":    {"food": 7, "space": 8, "contamination": 0, "disease": 0},
            "tigrillo": {"food": 0, "space": 8, "contamination": 0, "disease": 0},
            "aguila":   {"food": 0, "space": 8, "contamination": 0, "disease": 0},
            "pajarito": {"food": 6, "space": 8, "contamination": 0, "disease": 0},
            "feral":    {"food": 0, "space": 8, "contamination": 0, "disease": 0},
            # Ecosistema de fondo: SIN presión por defecto (el mundo es su casa)
            "insecto":  {"food": 9, "space": 9, "contamination": 0, "disease": 0},
            "roedor":   {"food": 8, "space": 9, "contamination": 0, "disease": 0},
            "serpiente":{"food": 0, "space": 9, "contamination": 0, "disease": 0},
        }

    def set_config(self, species_id: str, values: dict) -> None:
        """Actualiza (parcialmente) la config de una especie desde la UI."""
        cfg = self._config.setdefault(species_id, {})
        for key in ("food", "space", "contamination", "disease"):
            if key in values:
                cfg[key] = max(0, min(10, int(values[key])))

    def get_config(self, species_id: str) -> dict:
        return dict(self._config.get(species_id, {}))

    def reproduction_factor(self, species_id: str) -> float:
        """Multiplicador de tasa de nacimientos según el espacio slider.

        space=10 -> 1.0 (natalidad completa); space=0 -> 0.0 (no nacen).
        El ReproductionSystem lo consulta por especie.
        """
        cfg = self._config.get(species_id, {})
        space = cfg.get("space", 8)
        return max(0.0, min(1.0, space / 10.0))

    def update(self, ctx: SystemContext) -> None:
        registry = ctx.registry
        half = self.world_size

        query = registry.query(SpeciesRef, Diet, Position, EnergyComponent)
        for _entity, sref, diet, pos, energy in query:
            if not sref.species_id:
                continue
            cfg = self._config.get(sref.species_id)
            if not cfg:
                continue

            drain = 0.0

            # Espacio: empuje al centro (el hábitat se encoge) — SIN matar.
            # El animal se reubica dentro del cuadrado habitable; su energía
            # no se ve afectada. Es un efecto de distribución territorial,
            # no de mortalidad: la cadena trófica no se entera.
            space = cfg.get("space", 8)
            if space < 10:
                inset = (10 - space) * SPACE_INSET
                lim = half - 1
                pos.x = max(inset, min(lim - inset, pos.x))
                pos.y = max(inset, min(lim - inset, pos.y))

            # Contaminación y enfermedad: drenaje directo.
            drain += cfg.get("contamination", 0) * CONTAM_DRAIN
            drain += cfg.get("disease", 0) * DISEASE_DRAIN

            # Comida (solo herbívoros): por debajo de 5 HAMBRUNA real (hasta
            # -25/tick, superando lo que el forrajeo puede recuperar: +20).
            # Por encima de 5, bonus moderado.
            if diet.diet_type is DietType.HERBIVORE:
                food = cfg.get("food", 5)
                if food < 5:
                    drain += (5 - food) * FOOD_STARVE
                else:
                    drain -= (food - 5) * FOOD_BONUS

            if drain > 0:
                energy.current_energy = max(
                    -999, min(energy.max_energy, int(energy.current_energy - drain))
                )
                # Causa diagnóstica: qué palanca por-especie domina el daño.
                if (
                    cfg.get("disease", 0) * DISEASE_DRAIN
                    >= cfg.get("contamination", 0) * CONTAM_DRAIN
                    and cfg.get("disease", 0)
                ):
                    energy.last_damage_source = "enfermedad"
                elif cfg.get("contamination", 0):
                    energy.last_damage_source = "contaminación"
                elif cfg.get("food", 5) < 5:
                    energy.last_damage_source = "hambre (poca comida)"
            elif drain < 0:
                # Bonus (comida abundante): cura sin tocar la causa.
                energy.current_energy = min(
                    energy.max_energy, int(energy.current_energy - drain)
                )
