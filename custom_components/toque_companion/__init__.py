"""Home Assistant integration for the official Toque Companion v1 API."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CompanionAuthError,
    CompanionError,
    CompanionProofError,
    ToqueCompanionClient,
)
from .const import CONF_PHONE_ID, CONF_ROBOT_ID, CONF_TOKEN, DOMAIN
from .coordinator import ToqueCompanionConfigEntry, ToqueCompanionCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant, entry: ToqueCompanionConfigEntry
) -> bool:
    """Set up Toque Companion from a config entry."""
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

    coordinator = ToqueCompanionCoordinator(hass, entry, client, initial_state)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ToqueCompanionConfigEntry
) -> bool:
    """Unload a config entry and cancel the long-poll task cleanly."""
    coordinator = entry.runtime_data
    await coordinator.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


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
