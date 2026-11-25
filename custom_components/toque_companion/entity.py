"""Base entity for Toque Companion."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROBOT_ID, DOMAIN
from .coordinator import ToqueCompanionCoordinator

MODEL_NAMES: dict[str, str] = {
    "mc-connect": "Monsieur Cuisine Connect",
    "mc-smart": "Monsieur Cuisine Smart",
}


def dig(data: dict[str, Any] | None, *keys: str) -> Any:
    """Safely traverse nested dicts, returning None if any key is missing."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class ToqueCompanionEntity(CoordinatorEntity[ToqueCompanionCoordinator]):
    """Base entity attached to the robot device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ToqueCompanionCoordinator,
        key: str,
        *,
        needs_base_sample: bool = False,
    ) -> None:
        super().__init__(coordinator)
        self._needs_base_sample = needs_base_sample
        self._attr_translation_key = key

        robot = coordinator.state.get("robot") or {}
        robot_id = (
            robot.get("id")
            or coordinator.config_entry.data.get(CONF_ROBOT_ID)
            or coordinator.config_entry.unique_id
            or coordinator.config_entry.entry_id
        )
        self._attr_unique_id = f"{robot_id}_{key}"

        model_id = str(robot.get("model") or "")
        model = MODEL_NAMES.get(model_id) or model_id or "Monsieur Cuisine"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(robot_id))},
            name=robot.get("name") or "Monsieur Cuisine",
            manufacturer="Silvercrest / Toque",
            model=model,
            sw_version=robot.get("appVersion") or None,
        )

    @property
    def available(self) -> bool:
        if not self.coordinator.robot_available:
            return False
        if self._needs_base_sample:
            return self.coordinator.base_data_valid
        return True
