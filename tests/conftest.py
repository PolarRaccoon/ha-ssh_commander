"""Test helpers that load the transport module without Home Assistant."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(scope="session")
def ssh_module() -> ModuleType:
    """Load const.py and ssh_client.py without executing integration __init__.py."""
    root = Path(__file__).parents[1] / "custom_components" / "ssh_commander"
    package_name = "custom_components.ssh_commander"

    custom_components = ModuleType("custom_components")
    custom_components.__path__ = [str(root.parent)]
    package = ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules[package_name] = package

    for module_name in ("const", "ssh_client"):
        qualified_name = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(
            qualified_name, root / f"{module_name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)

    return sys.modules[f"{package_name}.ssh_client"]
