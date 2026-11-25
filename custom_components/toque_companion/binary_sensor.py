"""Binary sensors for Toque Companion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ToqueCompanionConfigEntry, ToqueCompanionCoordinator
from .entity import ToqueCompanionEntity, dig

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ToqueCompanionBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description for Toque Companion."""

    value_fn: Callable[[ToqueCompanionCoordinator], bool | None]
    attrs_fn: Callable[[ToqueCompanionCoordinator], dict[str, Any] | None] | None = None
    needs_base_sample: bool = False


def _machine_flag(field: str) -> Callable[[ToqueCompanionCoordinator], bool | None]:
    def _read(c: ToqueCompanionCoordinator) -> bool | None:
        val = dig(c.state, "machine", field)
        return None if val is None else bool(val)

    return _read


BINARY_SENSORS: tuple[ToqueCompanionBinarySensorDescription, ...] = (
    ToqueCompanionBinarySensorDescription(
        key="lid_open",
        device_class=BinarySensorDeviceClass.OPENING,
        needs_base_sample=True,
        value_fn=_machine_flag("lidOpen"),
    ),
    ToqueCompanionBinarySensorDescription(
        key="bowl_present",
        icon="mdi:pot-mix",
        needs_base_sample=True,
        value_fn=_machine_flag("bowlDetected"),
    ),
    ToqueCompanionBinarySensorDescription(
        key="motor",
        device_class=BinarySensorDeviceClass.RUNNING,
        needs_base_sample=True,
        value_fn=_machine_flag("motorOn"),
    ),
    ToqueCompanionBinarySensorDescription(
        key="heater",
        device_class=BinarySensorDeviceClass.HEAT,
        needs_base_sample=True,
        value_fn=_machine_flag("heaterOn"),
    ),
    ToqueCompanionBinarySensorDescription(
        key="hot",
        device_class=BinarySensorDeviceClass.HEAT,
        needs_base_sample=True,
        value_fn=_machine_flag("hot"),
    ),
    ToqueCompanionBinarySensorDescription(
        key="scale_stable",
        icon="mdi:scale-balance",
        needs_base_sample=True,
        value_fn=_machine_flag("scaleStable"),
    ),
    ToqueCompanionBinarySensorDescription(
        key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: bool(dig(c.state, "machine", "faultCode")),
        attrs_fn=lambda c: (
            {
                "code": dig(c.state, "machine", "faultCode"),
                "message": dig(c.state, "machine", "faultMessage"),
            }
            if dig(c.state, "machine", "faultCode")
            else None
        ),
    ),
    ToqueCompanionBinarySensorDescription(
        key="turbo",
        device_class=BinarySensorDeviceClass.RUNNING,
        needs_base_sample=True,
        entity_registry_enabled_default=False,
        value_fn=_machine_flag("turbo"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToqueCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Toque Companion binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        ToqueCompanionBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    )


class ToqueCompanionBinarySensor(ToqueCompanionEntity, BinarySensorEntity):
    """Binary sensor entity backed by Toque Companion state."""

    entity_description: ToqueCompanionBinarySensorDescription

    def __init__(
        self,
        coordinator: ToqueCompanionCoordinator,
        description: ToqueCompanionBinarySensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            description.key,
            needs_base_sample=description.needs_base_sample,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator)
