"""Home Assistant integration for the official Toque Companion v1 API."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CompanionAuthError,
    CompanionError,
    CompanionProofError,
    ToqueCompanionClient,
)
from .const import (
    CONF_PHONE_ID,
    CONF_ROBOT_ID,
    CONF_SENSOR_ONLY,
    CONF_TOKEN,
    DOMAIN,
)
from .coordinator import ToqueCompanionConfigEntry, ToqueCompanionCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_ONLY_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
]

FULL_PLATFORMS: list[Platform] = [
    *SENSOR_ONLY_PLATFORMS,
    Platform.BUTTON,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _platforms_for_entry(entry: ToqueCompanionConfigEntry) -> list[Platform]:
    if entry.data.get(CONF_SENSOR_ONLY, False):
        return SENSOR_ONLY_PLATFORMS
    return FULL_PLATFORMS


async def async_setup_entry(
    hass: HomeAssistant, entry: ToqueCompanionConfigEntry
) -> bool:
    """Set up Toque Companion from a config entry."""
    sensor_only = bool(entry.data.get(CONF_SENSOR_ONLY, False))
    client = ToqueCompanionClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        token=entry.data[CONF_TOKEN],
        phone_id=entry.data[CONF_PHONE_ID],
        robot_id=entry.data[CONF_ROBOT_ID],
    )

    try:
        initial_state = await client.get_state()
    except CompanionAuthError as err:
        raise ConfigEntryAuthFailed("Robot rejected pairing token") from err
    except CompanionProofError as err:
        raise ConfigEntryNotReady(
            f"Robot identity proof failed at {entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}; "
            "the robot IP may have changed or this client may have been removed on the robot"
        ) from err
    except CompanionError as err:
        raise ConfigEntryNotReady(
            f"Cannot reach Toque Companion at {entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}: {err}"
        ) from err

    if sensor_only:
        # Remove previously registered button entities when switching to sensor-only mode
        ent_reg = er.async_get(hass)
        for reg_entry in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
            if reg_entry.domain == Platform.BUTTON:
                ent_reg.async_remove(reg_entry.entity_id)

    coordinator = ToqueCompanionCoordinator(
        hass, entry, client, initial_state, sensor_only=sensor_only
    )
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )
    coordinator.async_start()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ToqueCompanionConfigEntry
) -> bool:
    """Unload a config entry and cancel the long-poll task cleanly."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return True
    await coordinator.async_stop()
    platforms = SENSOR_ONLY_PLATFORMS if coordinator.sensor_only else FULL_PLATFORMS
    return await hass.config_entries.async_unload_platforms(entry, platforms)


async def async_remove_entry(
    hass: HomeAssistant, entry: ToqueCompanionConfigEntry
) -> None:
    """Best-effort unpair (DELETE /api/phones/me) to free one of the robot's 8 client slots."""
    try:
        client = ToqueCompanionClient(
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            token=entry.data[CONF_TOKEN],
            phone_id=entry.data[CONF_PHONE_ID],
            robot_id=entry.data[CONF_ROBOT_ID],
            connect_timeout=3.0,
            read_timeout=5.0,
        )
        await client.forget()
    except Exception as err:  # noqa: BLE001 - best-effort cleanup on entry deletion
        _LOGGER.debug(
            "Best-effort unpair skipped/failed during entry removal: %s",
            type(err).__name__,
        )
