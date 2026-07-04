# Arquitectura General del Proyecto

Este documento describe la estructura general, las responsabilidades, el flujo de información y los puntos de escalabilidad clave para el "Population Simulator".

## 1. Estructura de Carpetas y Responsabilidades

El proyecto se organiza en una estructura modular y clara para separar las preocupaciones:

```
PopulationSimulator/
├── backend/                  # Lógica del servidor, motor de simulación y gestión de datos.
│   ├── engine/               # Contiene el corazón de la simulación.
│   │   ├── simulation.py     # Orquestador principal del ciclo de simulación (tick).
│   │   ├── animal.py         # Clase base para todos los animales y su lógica de comportamiento genérica.
│   │   ├── environment.py    # Gestión del mapa, celdas y sus propiedades ambientales.
│   │   ├── resources.py      # Gestión de la biomasa, tipos de alimento y su regeneración.
│   │   ├── reproduction.py   # Lógica genérica de reproducción para todas las especies.
│   │   ├── diseases.py       # Sistema de propagación y efectos de enfermedades.
│   └── weather.py        # Generación y actualización de las condiciones climáticas.
│   ├── species/              # Módulos para organizar definiciones de especies, no lógica.
│   │   ├── birds/            # Archivos de configuración/parámetros para aves.
│   │   ├── mammals/          # Archivos de configuración/parámetros para mamíferos.
│   │   ├── reptiles/         # Archivos de configuración/parámetros para reptiles.
│   │   ├── amphibians/       # Archivos de configuración/parámetros para anfibios.
│   │   ├── fish/             # Archivos de configuración/parámetros para peces.
│   │   └── insects/          # Archivos de configuración/parámetros para insectos.
│   ├── database/             # Contiene la base de datos y scripts de gestión de datos.
│   │   ├── simulator.db      # Base de datos SQLite para especies, biomas, recursos, etc.
│   │   ├── species_loader.py # Script para cargar/exportar datos de especies desde/hacia la DB.
│   │   └── initial_data.json # Archivo JSON inicial para poblar la DB (opcional, para importación).
│   └── api.py                # Interfaz RESTful para la comunicación con el frontend (Flask/FastAPI).
├── frontend/                 # Interfaz de usuario interactiva y visualización.
│   ├── html/                 # Archivos HTML (estructura de la interfaz).
│   │   └── index.html
│   ├── css/                  # Hojas de estilo CSS (apariencia de la interfaz).
│   │   └── style.css
│   └── js/                   # Scripts JavaScript (lógica interactiva y comunicación con el backend).
│       └── main.js
├── assets/                   # Recursos multimedia para el frontend.
│   ├── animals/              # Imágenes o sprites de animales.
│   ├── backgrounds/          # Imágenes de fondos dinámicos por bioma/altitud.
│   └── icons/                # Iconos para la interfaz de usuario.
└── docs/                     # Documentación del proyecto (diseño, manuales, etc.).
```

## 2. Flujo de Información y Comunicación

### Backend Interno

-   **`api.py`** es el punto de entrada para las solicitudes del frontend.
-   **`api.py`** interactúa con el **`engine/simulation.py`** para iniciar, pausar, acelerar la simulación y obtener datos del estado actual.
-   El **`engine/simulation.py`** orquesta a todos los demás módulos del `engine` (animal, environment, resources, etc.) para ejecutar cada "tick" de simulación.
-   Los módulos dentro de `engine` se comunican entre sí:
    -   `animal.py` (instancias de animales) interactúa con `environment.py` para obtener datos de celda, `resources.py` para consumir alimentos, `reproduction.py` para la lógica de apareamiento, `diseases.py` para efectos de salud.
    -   `environment.py` consulta `weather.py` para las condiciones climáticas y `resources.py` para la biomasa disponible.
-   La carpeta `species/` contiene definiciones de parámetros que son leídas por `animal.py` o `simulation.py` al inicializar las especies, pero no contiene lógica de comportamiento.
-   `database/simulator.db` es consultado por `api.py` o `simulation.py` para cargar los parámetros de las especies y el entorno.

### Comunicación Frontend-Backend

Se utilizará una API RESTful (con Flask o FastAPI) para la comunicación.

-   **Frontend (JavaScript)**: Envía solicitudes HTTP (GET, POST, PUT) al backend.
-   **Backend (`api.py`)**: Recibe las solicitudes, las procesa (ejecutando comandos del motor, consultando la DB), y devuelve respuestas JSON.

**Ejemplos de Endpoints (API REST):**

-   `GET /simulation/status`: Obtener el estado actual de la simulación (pausada, corriendo, velocidad).
-   `POST /simulation/start`: Iniciar la simulación.
-   `POST /simulation/pause`: Pausar la simulación.
-   `POST /simulation/speed`: Ajustar la velocidad de la simulación.
-   `GET /simulation/data`: Obtener los datos actuales del mapa y los animales para la visualización.
-   `GET /species`: Obtener la lista de todas las especies.
-   `GET /species/{species_id}`: Obtener los detalles y parámetros de una especie específica.
-   `PUT /species/{species_id}`: Actualizar los parámetros de una especie.
-   `GET /stats`: Obtener datos para los gráficos en tiempo real.

## 3. Funcionamiento del Motor de Simulación (Unificado por Parámetros)

El motor de simulación (`simulation.py`) es el orquestador principal. Su principio clave es la **emergencia del comportamiento a partir de parámetros**, no de lógica específica para cada especie.

1.  **Ciclo de "Tick"**: El motor ejecuta un bucle continuo, donde cada iteración es un "tick" de tiempo de simulación.
2.  **Actualización Global**: En cada tick, el motor actualiza primero factores globales (clima, recursos, enfermedades).
3.  **Iteración de Animales**: Luego, el motor itera sobre *todos* los individuos animales presentes en el simulador.
4.  **Lógica Parametrizada**: Para cada animal, el motor llama a métodos genéricos de la clase `Animal` (ej. `update_hunger()`, `move()`, `reproduce()`).
5.  **Interacciones**: Estos métodos utilizan los *parámetros específicos* de la especie del animal (leídos desde la base de datos) y las *condiciones actuales del entorno* (`environment.py`, `resources.py`) para determinar su comportamiento.
    -   Si un animal tiene `can_fly: true` y `flight_altitude > 0`, su método `move()` considerará el movimiento aéreo.
    -   Si `diet_type: "carnivore"` y `hunt_skill > X`, su método `seek_food()` buscará presas y ejecutará lógica de caza.
    -   Si `needs_water: true` y `humidity < threshold`, su método `seek_water()` lo impulsará a buscar celdas con agua.
6.  **Máquina de Estados Universal**: Los animales transicionan entre estados predefinidos (Buscar comida, Cazar, Dormir, etc.) basándose en sus necesidades y los parámetros de su especie. La lógica de transición está en el motor o la clase `Animal`, no en las especies.

## 4. Cómo se Agregan Nuevas Entidades

### Nuevas Especies

1.  **Definición de Parámetros**: Se crea una nueva entrada en la base de datos SQLite (tabla `species`) con todos los parámetros biológicos, conductuales y de hábitat de la nueva especie. No se necesita escribir código Python adicional ni modificar el motor.
2.  **Assets (Opcional)**: Se añade una imagen de caricatura para la especie en `assets/animals/`.
3.  **Lógica Emergentemente**: El motor de simulación, al cargar estos parámetros, aplicará automáticamente su lógica genérica. Si una nueva variable o tipo de comportamiento es realmente novedoso, podría requerir una extensión en la clase base `Animal` o en los módulos del `engine`, pero esto sería para funcionalidad *general*, no específica de la especie.

### Nuevos Biomas

1.  **Definición de Parámetros**: Se añade una nueva entrada en la base de datos SQLite (tabla `biomes`) con las características ambientales promedio (temperatura, humedad, tipos de recursos, capacidad de carga).
2.  **Representación Visual (Opcional)**: Se añade una imagen de fondo correspondiente en `assets/backgrounds/`.
3.  **Generación del Mapa**: Al generar un nuevo mapa o extender el existente, se asignan celdas al nuevo bioma, poblando sus propiedades según los parámetros definidos.
4.  **Interacción**: El motor de simulación ya está diseñado para que los animales interactúen con las propiedades de la celda (temperatura, recursos, etc.), por lo que el nuevo bioma simplemente presenta un nuevo conjunto de condiciones para que la lógica emergente actúe.

### Nuevos Recursos (Tipos de Alimento, etc.)

1.  **Definición de Parámetros**: Se añade una nueva entrada en la base de datos SQLite (tabla `resource_types`) con propiedades como biomasa, regeneración, tipo de alimento, toxicidad, estacionalidad.
2.  **Integración en Celdas**: Las celdas del entorno (a través de `environment.py` y `resources.py`) pueden ser configuradas para contener instancias de estos nuevos tipos de recursos.
3.  **Interacción Animal**: Las especies animales se definirán en la DB con preferencias dietéticas (ej., `diet_consumes: ["tipo_bay-nueva"]`). El motor, a través de la lógica genérica de `seek_food()`, sabrá cómo los animales interactúan con este nuevo recurso basándose en sus parámetros de dieta.
