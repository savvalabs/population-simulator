"""Population Engine.

A headless, data-driven ecological simulation engine. Behaviour emerges from
the composition of parameters (ECS components) and mathematical models, not
from per-species logic. The engine is independent of any client; UIs are just
observers/controllers of an otherwise long-running headless process.

The importable package name is ``population_engine`` so it never collides with
the generic word "engine" elsewhere.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
