# Diseño de Clases (CLASS_DESIGN.md)

Este documento detalla el diseño de las clases principales del motor de simulación, enfatizando la Programación Orientada a Objetos (POO) y el principio de que **el comportamiento emerge de los parámetros**, no de la lógica hardcodeada en subclases de especies. Las subclases de especies contendrán principalmente las definiciones de sus parámetros por defecto.

## 1. Clase Base: `Animal` (en `backend/engine/animal.py`)

La clase `Animal` es la base para todos los individuos en el simulador. Contiene todas las variables de estado y métodos genéricos de comportamiento que cualquier animal podría necesitar. Estos métodos utilizarán los parámetros de la especie cargados para determinar su acción.

**Atributos de Instancia (Variables de todos los animales):**

-   `id`: `str` (UUID único del individuo)
-   `name`: `str` (Nombre del individuo, ej. "Jaguar-001")
-   `species_name`: `str` (Nombre de la especie, ej. "Jaguar")
-   `group`: `str` (Grupo taxonómico, ej. "Mamíferos")
-   `position_x`: `int`
-   `position_y`: `int`
-   `hp`: `int` (Puntos de Salud, 0-100)
-   `hunger`: `int` (Nivel de hambre, 0-100)
-   `thirst`: `int` (Nivel de sed, 0-100)
-   `energy`: `int` (Nivel de energía, 0-100)
-   `age`: `int` (Edad en ticks o días simulados)
-   `sex`: `str` ("Macho" / "Hembra")
-   `gestation_timer`: `int` (Contador para gestación/incubación, 0 si no está gestando)
-   `current_state`: `str` (Estado actual según la Máquina de Estados Universal, ej. "Buscar_Comida")
-   `memory`: `dict` (Para almacenar ubicaciones recientes de recursos, depredadores, etc.)
-   `territory_center_x`: `int` (Centro del territorio del individuo/pareja)
-   `territory_center_y`: `int` (Centro del territorio del individuo/pareja)
-   `partner_id`: `str` (ID del compañero, si es monógamo)
-   `infection_status`: `dict` (Ej. `{"disease_id": "gripe_aviaria", "severity": 0.5}` si está infectado, `None` si no)

**Atributos de Clase (Parámetros de la especie, cargados desde la DB e inmutables para la especie):**

Estos parámetros se cargarán en la instancia del animal al ser creado, pero reflejarán los valores de su especie. No son modificables por el individuo directamente, sino por el usuario a nivel de especie.

-   `max_hp`: `int`
-   `max_hunger`: `int`
-   `max_thirst`: `int`
-   `max_energy`: `int`
-   `max_age`: `int` (Esperanza de vida máxima)
-   `metabolic_rate`: `float` (Tasa de aumento de hambre/sed por tick)
-   `base_energy_cost`: `float` (Costo de energía por tick)
-   `speed`: `int` (Velocidad de movimiento base)
-   `flight_speed`: `int` (Velocidad de movimiento si vuela)
-   `swim_speed`: `int` (Velocidad de movimiento si nada)
-   `vision_range`: `int`
-   `diet_type`: `str` ("Herbivore", "Carnivore", "Omnivore", "Scavenger")
-   `diet_consumes`: `list` (Lista de tipos de recursos/especies que consume)
-   `hunt_skill`: `int` (Habilidad de caza)
-   `escape_skill`: `int` (Habilidad de escape)
-   `reproduction_rate`: `float` (Probabilidad base de reproducción)
-   `gestation_time`: `int` (Ticks para gestación/incubación)
-   `litter_size`: `int` (Tamaño de la camada/nidada)
-   `mating_season_start`: `int` (Mes de inicio de temporada)
-   `mating_season_end`: `int` (Mes de fin de temporada)
-   `monogamous`: `bool`
-   `parental_care_duration`: `int` (Ticks de cuidado parental)
-   `min_reproduction_age`: `int`
-   `temperature_tolerance_min`: `int`
-   `temperature_tolerance_max`: `int`
-   `humidity_tolerance_min`: `int`
-   `humidity_tolerance_max`: `int`
-   `can_fly`: `bool`
-   `can_swim`: `bool`
-   `aquatic`: `bool` (Si solo puede vivir en agua)
-   `stealth`: `int` (Habilidad de sigilo)
-   `strength`: `int` (Fuerza para caza/combate)
-   `territory_size`: `int` (Radio del territorio)
-   `scavenger_perception_range`: `int` (Para carroñeros)
-   `flight_altitude_min`: `int` (Si vuela)
-   `flight_altitude_max`: `int` (Si vuela)
-   `gliding_efficiency`: `float` (Si vuela)
-   `water_needs`: `float` (Necesidad de agua)
-   `prey_species`: `list` (Lista de especies que caza, para depredadores)
-   `predator_species`: `list` (Lista de especies que lo cazan, para presas)
-   `disease_resistance`: `float`
-   `infant_survival_rate_base`: `float` (Tasa de supervivencia de crías sin cuidado parental)

**Métodos Genéricos de Comportamiento (Lógica del Motor, aplicada por `simulation.py`):**

Estos métodos son llamados por el motor para *todos* los animales. Internamente, usan los atributos de instancia y los parámetros de la especie para decidir qué hacer.

-   `update_state(environment, resources)`: Actualiza `current_state` basado en necesidades, entorno y parámetros.
-   `update_metabolism()`: Disminuye `hunger`, `thirst`, `energy`. Reduce `hp` si las necesidades son críticas.
-   `move(environment)`: Calcula y actualiza `position_x, position_y` según `current_state`, `speed`, `can_fly`, `aquatic`, `territory_size` y `vision_range`.
-   `seek_food(environment, resources)`: Busca alimento según `diet_type`, `diet_consumes`, `vision_range`. Si lo encuentra, consume y reduce `hunger`.
-   `seek_water(environment)`: Busca agua si `thirst` es alto.
-   `hunt(target_animal, environment)`: Inicia la secuencia de caza contra `target_animal` (si es carnívoro).
-   `flee(predator_animal)`: Intenta escapar de `predator_animal` (si es presa).
-   `reproduce(environment)`: Lógica para buscar pareja, gestar y dar a luz, utilizando `reproduction_rate`, `gestation_time`, `litter_size`.
-   `update_age()`: Incrementa la `age`.
-   `update_health()`: Gestiona recuperación de `hp` y efectos de `infection_status`.
-   `check_death()`: Determina si el animal muere por `hp`, `age`, o condiciones ambientales extremas.
-   `interact_with_cell(cell_data)`: Reacciona a las propiedades de la celda actual (temperatura, humedad, bioma).
-   `get_visible_entities(environment)`: Devuelve una lista de animales/recursos visibles dentro de `vision_range`.

## 2. Clases de Entorno (en `backend/engine/environment.py`)

### `Cell`

Representa una unidad atómica del mapa, conteniendo todas las propiedades ambientales y de recursos.

**Atributos:**

-   `x`: `int`
-   `y`: `int`
-   `altitude`: `int`
-   `temperature`: `float`
-   `humidity`: `float`
-   `precipitation`: `float`
-   `biome_type`: `str` (ej. "Bosque Tropical", "Páramo")
-   `water_level`: `float` (Disponibilidad de agua en la celda)
-   `slope`: `float` (Pendiente del terreno)
-   `carrying_capacity_vegetation`: `float` (K para biomasa vegetal)
-   `vegetation_biomass`: `dict` (Ej. `{"grass": 50, "shrubs": 20}`)
-   `resource_types_present`: `list` (Tipos de recursos comestibles en la celda)
-   `toxicity_level`: `float`
-   `seasonal_factor`: `float` (Influencia de la estación en recursos/clima de esta celda)
-   `animal_ids_present`: `list` (IDs de animales actualmente en esta celda)

### `Environment`

Gestiona la cuadrícula de celdas, la generación del mapa y las interacciones a nivel de mapa.

**Atributos:**

-   `grid`: `list[list[Cell]]` (Matriz 2D de objetos `Cell`)
-   `width`: `int`
-   `height`: `int`
-   `global_weather_patterns`: `dict` (Parámetros para `weather.py`)
-   `biomes_data`: `dict` (Cargado de la DB, con propiedades de cada bioma)

**Métodos:**

-   `generate_map(width, height, biomes_config)`: Crea la cuadrícula de celdas con altitudes, biomas y recursos iniciales.
-   `get_cell(x, y)`: Devuelve el objeto `Cell` en las coordenadas dadas.
-   `update_cell_resources(current_tick_data)`: Actualiza los recursos de todas las celdas (llama a `resources.py`).
-   `update_cell_weather(current_weather_data)`: Aplica las nuevas condiciones climáticas a las celdas (llama a `weather.py`).
-   `get_nearby_cells(x, y, radius)`: Devuelve un iterador de celdas cercanas para búsquedas de visión.

## 3. Clases de Recursos (en `backend/engine/resources.py`)

### `Resource`

Clase base para representar un recurso comestible o esencial.

**Atributos:**

-   `type`: `str` (ej. "Grass", "Berries", "Carrion", "Water")
-   `current_biomass`: `float` (Cantidad actual disponible)
-   `max_biomass`: `float` (Capacidad máxima)
-   `regeneration_rate`: `float`
-   `nutritional_value`: `float` (Puntos de hambre/energía que repone)
-   `toxicity`: `float`
-   `season_effect_factor`: `dict` (Ej. `{"dry": 0.5, "rainy": 1.2}`)

**Métodos:**

-   `consume(amount)`: Reduce `current_biomass` y devuelve la cantidad consumida.
-   `regenerate(weather_conditions, seasonal_data)`: Aumenta `current_biomass` hasta `max_biomass`.

### `ResourceManager` (Posiblemente integrado en `simulation.py` o `environment.py`)

Gestiona la creación, actualización y consulta de recursos en el mapa.

**Métodos:**

-   `get_resources_in_cell(cell_x, cell_y)`: Devuelve los `Resource` disponibles en una celda.
-   `update_all_resources(environment, current_season)`: Llama a `regenerate()` para todos los recursos.

## 4. `Simulation` (en `backend/engine/simulation.py`)

Clase principal que orquesta el bucle de simulación, gestiona todas las instancias de animales y el entorno.

**Atributos:**

-   `current_tick`: `int`
-   `global_time`: `dict` (`day`, `month`, `year`, `season`)
-   `all_animals`: `dict` (Mapa de `id` de animal a objeto `Animal`)
-   `environment`: `Environment` (Instancia del entorno)
-   `is_running`: `bool`
-   `speed_multiplier`: `int`
-   `global_diseases`: `list` (Lista de objetos `Disease` activos)
-   `global_parameters`: `dict` (Deforestación, caza furtiva, cambio climático, etc.)
-   `species_parameters`: `dict` (Cargados de la DB)
-   `biomes_parameters`: `dict` (Cargados de la DB)

**Métodos:**

-   `__init__(config_data)`: Inicializa el entorno, carga especies y crea animales iniciales.
-   `start()`, `pause()`, `set_speed(multiplier)`: Control de la simulación.
-   `run_tick()`: Ejecuta un ciclo completo de simulación (ver `SIMULATION_ENGINE.md`).
-   `add_animal(species_name, x, y, sex)`: Crea y añade un nuevo animal.
-   `remove_animal(animal_id)`: Elimina un animal.
-   `get_simulation_data()`: Devuelve el estado actual para el frontend.
-   `get_statistics()`: Recopila y devuelve estadísticas.
-   `load_parameters_from_db()`: Carga todos los parámetros de la base de datos.

## 5. Subclases de Especies (en `backend/species/`)

**No contienen lógica de comportamiento propia.** Su función principal es servir como "plantillas" para cargar parámetros por defecto o realizar pequeñas sobreescrituras de parámetros en tiempo de inicialización si fuera *absolutamente necesario* y justificado para un grupo muy específico (ej. un `Bird` podría tener `can_fly=True` por defecto). Sin embargo, la intención es que incluso esto se maneje en la base de datos.

Ejemplo (Conceptual, la mayoría de estos valores se cargarían desde la DB):

```python
# backend/species/birds/condor.py (NO contendrá métodos de comportamiento)
class Condor(Animal):
    def __init__(self, id, name, x, y, sex, species_params=None):
        # species_params contendrá los datos cargados de la DB para el Cóndor
        super().__init__(id, name, "Condor", "Birds", x, y, sex, species_params)
        # Cualquier parámetro específico que no pueda venir directamente de la DB
        # o una sobreescritura muy especial, pero la idea es evitar esto.

# Los parámetros REALMENTE vivirán en la base de datos SQLite
# y se pasarán a la clase base Animal al inicializar la instancia.
```

La `Simulation` creará instancias de `Animal` pasando los parámetros de la especie correspondiente (ej. "Cóndor") cargados desde la DB. No instanciará `Condor`, sino `Animal` con los parámetros del cóndor. Esto asegura un motor unificado.
