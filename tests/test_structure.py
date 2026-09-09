"""Structural smoke tests for the population_engine package layout.

These verify the package skeleton (step 1 of implementation): the importable
package exists, exposes a version, and the agreed subpackages are importable
and each documents its purpose. Runnable standalone or via pytest:

    py -m tests.test_structure
    pytest tests/test_structure.py
"""

from __future__ import annotations

import importlib

import population_engine

EXPECTED_SUBPACKAGES = (
    "core",
    "ecs",
    "world",
    "models",
    "systems",
    "plugins",
    "data",
)


def test_version_present() -> None:
    assert isinstance(population_engine.__version__, str)
    assert population_engine.__version__


def test_top_level_docstring_present() -> None:
    assert population_engine.__doc__
    assert "Population Engine" in population_engine.__doc__


def test_subpackages_importable() -> None:
    for sub in EXPECTED_SUBPACKAGES:
        full = f"population_engine.{sub}"
        mod = importlib.import_module(full)
        assert mod is not None, f"failed to import {full}"
        assert mod.__doc__, f"{full} must document its package purpose"


def _run_standalone() -> int:
    failures = 0
    for name, obj in list(globals().items()):
        if name.startswith("test_") and callable(obj):
            try:
                obj()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001 - intentional broad handler
                failures += 1
                print(f"FAIL {name}: {exc!r}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_standalone() else 0)
