"""Diagnostics support for Toque Companion with strict credential redaction."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_PHONE_ID, CONF_ROBOT_ID, CONF_TOKEN
from .coordinator import ToqueCompanionConfigEntry

TO_REDACT: frozenset[str] = frozenset(
    {
        CONF_TOKEN,
        CONF_PHONE_ID,
        CONF_HOST,
        "token",
        "secret",
        "code",
        "phoneId",
        "phone_id",
        "authorization",
    }
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ToqueCompanionConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry with all secrets redacted."""
    coordinator = entry.runtime_data
    state = dict(coordinator.state)
    # Redact paired phone identity block explicitly as well
    if isinstance(state.get("me"), dict):
        state["me"] = {
            "number": state["me"].get("number"),
            "method": state["me"].get("method"),
        }
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "robot_id_present": bool(entry.data.get(CONF_ROBOT_ID)),
        "sensor_only": coordinator.sensor_only,
        "robot_available": coordinator.robot_available,
        "base_data_valid": coordinator.base_data_valid,
        "last_error": coordinator.last_error,
        "state": async_redact_data(state, TO_REDACT),
    }
