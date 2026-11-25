"""Shared pytest fixtures for Toque Companion tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
import importlib.util
from pathlib import Path
import sys
import types

import pytest

_HAS_HA = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None

if not _HAS_HA and "custom_components.toque_companion" not in sys.modules:
    # Allow importing pure-Python submodules (const.py, api.py) in environments
    # without Home Assistant installed, without modifying production __init__.py.
    _root = Path(__file__).resolve().parent.parent
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [str(_root / "custom_components")]
    _pkg = types.ModuleType("custom_components.toque_companion")
    _pkg.__path__ = [str(_root / "custom_components" / "toque_companion")]
    sys.modules["custom_components"] = _cc
    sys.modules["custom_components.toque_companion"] = _pkg

from .fake_companion import FakeCompanionServer  # noqa: E402

if _HAS_HA:
    pytest_plugins = "pytest_homeassistant_custom_component"

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Enable loading custom_components in Home Assistant tests."""
        return

    @pytest.fixture
    async def fake_robot(socket_enabled) -> AsyncIterator[FakeCompanionServer]:
        server = FakeCompanionServer()
        await server.start()
        try:
            yield server
        finally:
            await server.stop()

    if sys.platform == "win32":
        import pytest_socket

        pytest_socket.disable_socket = lambda *args, **kwargs: None
