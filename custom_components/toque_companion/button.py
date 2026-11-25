"""Safe control buttons for Toque Companion: pause, stop, and tare only.

Availability strictly tracks the robot's authoritative `state.can.<action>.allowed`.
Remote start, resume, adjust, Turbo, or safety overrides are intentionally omitted.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ToqueCompanionConfigEntry, ToqueCompanionCoordinator
from .entity import ToqueCompanionEntity, dig

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ToqueCompanionButtonDescription(ButtonEntityDescription):
    """Button description mapping to an allowed Companion machine action."""

    action: str


BUTTONS: tuple[ToqueCompanionButtonDescription, ...] = (
    ToqueCompanionButtonDescription(
        key="pause",
        action="pause",
        icon="mdi:pause-circle-outline",
    ),
    ToqueCompanionButtonDescription(
        key="stop",
        action="stop",
        icon="mdi:stop-circle-outline",
    ),
    ToqueCompanionButtonDescription(
        key="tare",
        action="tare",
        icon="mdi:scale-balance",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToqueCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up safe control buttons."""
    coordinator = entry.runtime_data
    async_add_entities(ToqueCompanionButton(coordinator, desc) for desc in BUTTONS)


class ToqueCompanionButton(ToqueCompanionEntity, ButtonEntity):
    """Control button whose availability strictly follows `state.can.<action>.allowed`."""

    entity_description: ToqueCompanionButtonDescription

    def __init__(
        self,
        coordinator: ToqueCompanionCoordinator,
        description: ToqueCompanionButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key, needs_base_sample=False)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return bool(
            dig(self.coordinator.state, "can", self.entity_description.action, "allowed")
        )

    async def async_press(self) -> None:
        await self.coordinator.async_machine_action(self.entity_description.action)
