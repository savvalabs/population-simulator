# Motor de Simulación (SIMULATION_ENGINE.md)

Este documento describe el funcionamiento detallado del motor de simulación, explicando el ciclo de vida de un "tick" y la lógica que se aplica en cada etapa para todos los individuos del ecosistema.

El principio fundamental es que **el comportamiento de los animales emerge de sus parámetros y las condiciones del entorno**, no de lógica codificada específicamente para cada especie. El motor es el único que contiene la lógica de actualización.

## Ciclo de un "Tick" (Bucle Principal)

Cada "tick" de simulación representa una unidad de tiempo (ej. 15 minutos, 1 hora en tiempo simulado) y sigue la siguiente secuencia de actualización:

1.  **Actualizar Variables Globales**
2.  **Actualizar Clima (Weather)**
3.  **Actualizar Recursos (Resources)**
4.  **Actualizar Enfermedades (Diseases)**
5.  **Actualizar Animales (Estado y Comportamiento)**
    a.  Inicializar / Reaccionar al entorno
    b.  Actualizar Metabolismo (Hambre, Sed, Energía)
    c.  Evaluar Reproducción
    d.  Evaluar Movimiento (y Búsqueda)
    e.  Evaluar Caza / Escape
    f.  Evaluar Enfermedades / Salud
    g.  Evaluar Envejecimiento y Muerte
6.  **Actualizar Estadísticas**

--- 

### 1. Actualizar Variables Globales

-   **Objetivo**: Progresar el tiempo simulado y actualizar factores macro que afectan a todo el ecosistema.
-   **Módulos Afectados**: `simulation.py`
-   **Lógica**: Incrementa el `tiempo_simulado` (día, mes, año, estación). Actualiza variables como `deforestacion`, `caza_furtiva`, `presencia_humana`, `cambio_climatico` según modelos predefinidos o eventos externos (futura expansión).

### 2. Actualizar Clima (Weather)

-   **Objetivo**: Determinar las condiciones climáticas para cada celda del mapa.
-   **Módulos Afectados**: `weather.py`, `environment.py`
-   **Lógica**: El módulo `weather.py` genera nuevas condiciones (temperatura, humedad, precipitación) basadas en la estación actual, altitud del bioma y patrones históricos/modelos climáticos. Estas condiciones se aplican a las `Cell` correspondientes en `environment.py`.
    -   Ej: `temperatura_celda = base_temp_bioma + variacion_estacional + variacion_altitud + variacion_aleatoria`.

### 3. Actualizar Recursos (Resources)

-   **Objetivo**: Gestionar la regeneración y el consumo de recursos (biomasa vegetal, agua) en cada celda.
-   **Módulos Afectados**: `resources.py`, `environment.py`
-   **Lógica**:
    -   **Regeneración de Biomasa**: Para cada celda, la `biomasa_vegetal` se regenera a una `tasa_regeneracion` (parámetro del bioma y tipo de recurso), influenciada por el `clima` (precipitación, temperatura) de la celda.
    -   **Consumo de Agua**: Los puntos de agua/humedad en una celda se reponen según la `precipitacion` y se evaporan según la `temperatura` y `humedad` del clima.
    -   **Estacionalidad**: Algunos recursos pueden tener fases de crecimiento/disponibilidad influenciadas por la `estacion` global.

### 4. Actualizar Enfermedades (Diseases)

-   **Objetivo**: Simular la aparición, propagación y efectos de enfermedades en la población animal.
-   **Módulos Afectados**: `diseases.py`, `animal.py`
-   **Lógica**:
    -   **Aparición**: Puede haber una pequeña probabilidad de que una enfermedad "aparezca" en un individuo o celda, o ser introducida por `presencia_humana`.
    -   **Propagación**: Los animales infectados pueden transmitir enfermedades a otros animales cercanos (por `contacto_fisico`, `compartir_recursos`, `vectores`), dependiendo de la `tasa_transmision` de la enfermedad y la `proximidad`.
    -   **Efectos**: Las enfermedades afectan el `HP` (salud), `energia` y `tasa_reproduccion` del animal infectado, aumentando su `mortalidad` si no se recupera. Algunos animales pueden desarrollar `inmunidad`.

### 5. Actualizar Animales (Estado y Comportamiento)

Este es el ciclo más complejo, donde cada individuo `Animal` es procesado.

**Bucle de individuos**: `For each animal in simulator:`

#### 5a. Inicializar / Reaccionar al entorno

-   **Objetivo**: Evaluar las condiciones inmediatas de la celda actual y ajustar estados o necesidades.
-   **Lógica**: Un animal verifica la `temperatura_celda`, `humedad_celda`, `tipo_bioma_celda`. Si estas condiciones están fuera de su `rango_tolerancia_temperatura` o `rango_tolerancia_humedad` (parámetros de especie), el animal puede entrar en un estado de `Estrés_Ambiental` o aumentar su `consumo_energia` por termorregulación.

#### 5b. Actualizar Metabolismo (Hambre, Sed, Energía)

-   **Objetivo**: Disminuir los niveles de recursos vitales y gestionar el consumo/generación de energía.
-   **Lógica**:
    -   **Hambre**: `animal.hunger += metabolic_rate` (parámetro de especie). Si `hunger > max_hunger`, `animal.hp` disminuye.
    -   **Sed**: `animal.thirst += water_loss_rate` (parámetro de especie, influenciado por `temperatura_celda`). Si `thirst > max_thirst`, `animal.hp` disminuye.
    -   **Energía**: `animal.energy -= base_energy_cost` (parámetro de especie) + costos por `movimiento`, `caza`, `reproduccion`. La energía se recupera al `Comer` o `Descansar`.

#### 5c. Evaluar Reproducción

-   **Objetivo**: Determinar si un animal está en condiciones de reproducirse, iniciar gestación o dar a luz.
-   **Módulos Afectados**: `reproduction.py`, `animal.py`
-   **Lógica**:
    -   **Condiciones**: Un animal (hembra) solo puede reproducirse si `edad >= edad_madurez_sexual`, `salud > umbral_salud_repro`, `energia > umbral_energia_repro` y si está en la `temporada_reproductiva` (parámetro de especie/global).
    -   **Búsqueda de Pareja**: Si es `monogamo` (parámetro), buscará pareja. Si no, buscará una oportunidad de apareamiento.
    -   **Gestación/Incubación**: Si se reproduce, `gestacion_actual` (variable de instancia) incrementa hasta `tiempo_gestacion` (parámetro). Al completar, nace una nueva cría (instancia de `Animal`) con parámetros heredados/aleatorios.
    -   **Cuidado Parental**: Si `cuidado_parental > 0`, la cría permanece cerca de los padres y su `supervivenci-infantil` mejora.

#### 5d. Evaluar Movimiento (y Búsqueda)

-   **Objetivo**: Determinar el nuevo `posicion_X, posicion_Y` del animal basándose en sus necesidades y parámetros.
-   **Módulos Afectados**: `animal.py`, `environment.py`
-   **Lógica**:
    -   **Prioridades**: El animal evalúa sus necesidades (`hunger`, `thirst`) y su `estado_actual` (`Buscar_Comida`, `Buscar_Agua`, `Migrar`, etc.).
    -   **Movimiento General**: Si no hay una necesidad apremiante, el animal se mueve aleatoriamente dentro de su `rango_territorial` (parámetro) o realiza un `movimiento_errante`.
    -   **Movimiento Dirigido**: Si `hunger` o `thirst` son altos, el animal utiliza su `vision_rango` (parámetro) y `memoria` para localizar celdas con `recursos` o `agua` y se mueve hacia ellas a `velocidad`.
    -   **Movimiento Específico**: Si `vuela: true` y está en estado `Planeando`, utilizará `velocidad_aerea` y `eficiencia_planeo`. Si `permanece_en_agua: true`, su movimiento estará restringido a celdas acuáticas.
    -   **Coste de Energía**: El movimiento consume `energia`, con un coste mayor para `velocidad_maxima` o `movimiento_aereo`.

#### 5e. Evaluar Caza / Escape

-   **Objetivo**: Resolver interacciones depredador-presa.
-   **Módulos Afectados**: `animal.py`, `resources.py`
-   **Lógica**:
    -   **Depredador (`estado: Cazar`)**:
        -   Si `diet_type: "carnivore"` y detecta `presa` dentro de `vision_rango`.
        -   Compara `fuerza`, `sigilo`, `velocidad_persecucion` (parámetros de depredador) con `velocidad`, `camuflaje`, `velocidad_huida` (parámetros de presa).
        -   Calcula `exito_caza` (parámetro, influenciado por la diferencia de atributos y `probabilidad_emboscada`).
        -   Si tiene éxito: `presa.hp = 0` (muere), `depredador.hunger -= calorias_presa`, `depredador.energia += recuperacion_energia`.
        -   Si falla: la presa huye. El depredador consume `energia` sin recompensa.
    -   **Presa (`estado: Huir`)**:
        -   Si detecta `depredador` dentro de `vision_rango`.
        -   Intenta huir en dirección opuesta al depredador a `velocidad_huida`. Puede usar `camuflaje` para reducir la `vision` del depredador.
        -   Si la huida tiene éxito, el depredador pierde el rastro.

#### 5f. Evaluar Enfermedades / Salud

-   **Objetivo**: Actualizar la `salud` del animal y manejar los efectos de las enfermedades.
-   **Módulos Afectados**: `animal.py`, `diseases.py`
-   **Lógica**:
    -   **Recuperación**: Si `salud < 100` y no está infectado, `salud` se recupera lentamente con el tiempo, influenciado por su `tasa_recuperacion` y `energia`.
    -   **Efectos de Enfermedad**: Si está infectado, la enfermedad reduce `HP` y `energia` según su `gravedad_enfermedad`. Puede llevar a la muerte si `HP` llega a cero.

#### 5g. Evaluar Envejecimiento y Muerte

-   **Objetivo**: Aumentar la `edad` del animal y determinar las condiciones de muerte.
-   **Lógica**:
    -   **Envejecimiento**: `animal.age` aumenta por cada tick (o cada cierto número de ticks si un tick es muy corto).
    -   **Muerte**: Un animal muere si:
        -   `animal.hp <= 0` (por depredación, enfermedad, inanición, deshidratación, vejez).
        -   `animal.age >= animal.max_age` (parámetro de especie, con variaciones aleatorias).
        -   Condiciones extremas del entorno (ej. `temperatura_celda` fuera de `rango_tolerancia` por mucho tiempo).
    -   Al morir, el animal es eliminado del simulador y su `biomasa` puede convertirse en `carroña` o `nutrientes` en la celda.

### 6. Actualizar Estadísticas

-   **Objetivo**: Recopilar datos agregados del simulador para la visualización en el frontend.
-   **Módulos Afectados**: `simulation.py`, `api.py` (para exponer los datos).
-   **Lógica**: Después de procesar todos los animales y el entorno en un tick, se calculan estadísticas globales y por especie:
    -   `poblacion_total`, `poblacion_por_especie`.
    -   `nacimientos_por_tick`, `muertes_por_tick`.
    -   `promedio_hambre_por_especie`, `promedio_salud_por_especie`.
    -   `biomasa_total_mapa`, `biomasa_por_bioma`.
    -   Estos datos se almacenan temporalmente o se agregan para ser consultados por el frontend a través de la API (`GET /stats`).
