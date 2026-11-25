"""Cooking alert event entity driven by Toque Companion /api/journal."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES
from .coordinator import ToqueCompanionConfigEntry, ToqueCompanionCoordinator
from .entity import ToqueCompanionEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToqueCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Toque Companion event entity."""
    async_add_entities([ToqueCompanionEventEntity(entry.runtime_data)])


class ToqueCompanionEventEntity(ToqueCompanionEntity, EventEntity):
    """Cooking events: waiting, step_end, job_end, pause, fault, temp_reached."""

    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: ToqueCompanionCoordinator) -> None:
        super().__init__(coordinator, "cooking", needs_base_sample=False)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_event_listener(self._on_alert))

    @callback
    def _on_alert(self, alert_type: str, data: dict[str, Any]) -> None:
        if alert_type in EVENT_TYPES:
            self._trigger_event(alert_type, data)
            self.async_write_ha_state()
