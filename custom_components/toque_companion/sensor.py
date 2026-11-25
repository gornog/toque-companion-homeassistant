"""Sensors for Toque Companion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LINK_STATES, ROBOT_STATUSES
from .coordinator import ToqueCompanionConfigEntry, ToqueCompanionCoordinator
from .entity import ToqueCompanionEntity, dig

PARALLEL_UPDATES = 0
STATE_MAX_LEN = 255


def _truncate(text: Any) -> str | None:
    if not text:
        return None
    text_str = str(text)
    if len(text_str) <= STATE_MAX_LEN:
        return text_str
    return text_str[: STATE_MAX_LEN - 1] + "…"


def _derive_status(c: ToqueCompanionCoordinator) -> str:
    machine = c.state.get("machine") or {}
    if machine.get("faultCode"):
        return "fault"
    job = c.state.get("job")
    if isinstance(job, dict):
        job_state = str(job.get("state") or "").lower()
        if job_state in ROBOT_STATUSES:
            return job_state
    return "idle"


def _temperature(c: ToqueCompanionCoordinator) -> int | None:
    machine = c.state.get("machine") or {}
    if not machine.get("hasSample"):
        return None
    if machine.get("tempKnown") is False:
        return None
    temp = machine.get("tempC")
    # Connect hardware reads 0 below 37 C; return None instead of a misleading 0 C
    if not isinstance(temp, int) or temp <= 0:
        return None
    return temp


def _target_temperature(c: ToqueCompanionCoordinator) -> int | None:
    val = dig(c.state, "machine", "targetTempC")
    return int(val) if isinstance(val, int) else None


def _weight(c: ToqueCompanionCoordinator) -> int | None:
    val = dig(c.state, "machine", "weightG")
    return int(val) if isinstance(val, int) else None


def _speed_level(c: ToqueCompanionCoordinator) -> int:
    job = c.state.get("job")
    if isinstance(job, dict) and job.get("state") in ("STARTING", "RUNNING", "PAUSED"):
        speed = job.get("speed")
        if isinstance(speed, int):
            return speed
    return 0


def _remaining_seconds(c: ToqueCompanionCoordinator) -> int | None:
    job = c.state.get("job")
    if not isinstance(job, dict):
        return None
    ms = job.get("remainingMs")
    if not isinstance(ms, (int, float)):
        return None
    return max(0, round(ms / 1000))


def _current_step_obj(c: ToqueCompanionCoordinator) -> dict[str, Any] | None:
    session = c.state.get("session")
    if not isinstance(session, dict):
        return None
    steps = session.get("steps")
    current = session.get("current")
    if not isinstance(steps, list) or not isinstance(current, int):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("index") == current:
            return step
    if 0 <= current < len(steps) and isinstance(steps[current], dict):
        return steps[current]
    return None


def _step_number(c: ToqueCompanionCoordinator) -> str | None:
    session = c.state.get("session")
    if not isinstance(session, dict):
        return None
    count = session.get("stepCount")
    current = session.get("current")
    if not isinstance(count, int) or count <= 0 or not isinstance(current, int):
        return None
    return f"{current + 1}/{count}"


def _link_state(c: ToqueCompanionCoordinator) -> str | None:
    link = str(dig(c.state, "machine", "link") or "").lower()
    return link if link in LINK_STATES else None


@dataclass(frozen=True, kw_only=True)
class ToqueCompanionSensorDescription(SensorEntityDescription):
    """Sensor description with value extractor and optional attributes."""

    value_fn: Callable[[ToqueCompanionCoordinator], Any]
    attrs_fn: Callable[[ToqueCompanionCoordinator], dict[str, Any] | None] | None = None
    needs_base_sample: bool = False


def _job_attrs(c: ToqueCompanionCoordinator) -> dict[str, Any] | None:
    job = c.state.get("job")
    if not isinstance(job, dict):
        return None
    pause = job.get("pause") if isinstance(job.get("pause"), dict) else None
    attrs: dict[str, Any] = {
        "kind": job.get("kind"),
        "kind_label": job.get("kindLabel"),
        "state": job.get("state"),
        "phase": (job.get("phaseIndex", 0) + 1) if job.get("phaseCount") else None,
        "phase_count": job.get("phaseCount"),
        "reverse": job.get("reverse"),
        "accessory": job.get("accessory"),
        "end_reason": job.get("endReason") or None,
    }
    if pause is not None:
        attrs["pause_reason"] = pause.get("reason")
        attrs["pause_label"] = pause.get("label")
        attrs["lid_opened_during_pause"] = pause.get("lidOpenedDuringPause")
    return attrs


def _recipe_attrs(c: ToqueCompanionCoordinator) -> dict[str, Any] | None:
    session = c.state.get("session")
    if not isinstance(session, dict):
        return None
    return {
        "recipe_id": session.get("recipeId"),
        "servings": session.get("servings"),
        "step_count": session.get("stepCount"),
        "waiting_for": session.get("waitingFor"),
    }


def _step_attrs(c: ToqueCompanionCoordinator) -> dict[str, Any] | None:
    step = _current_step_obj(c)
    if step is None:
        return None
    session = c.state.get("session") or {}
    machine = step.get("machine") if isinstance(step.get("machine"), dict) else None
    weigh = step.get("weigh") if isinstance(step.get("weigh"), dict) else None
    attrs: dict[str, Any] = {
        "text": step.get("text"),
        "waiting_for": session.get("waitingFor"),
    }
    if machine is not None:
        attrs["machine_summary"] = machine.get("summary")
    if weigh is not None:
        attrs["weigh_label"] = weigh.get("label")
        attrs["weigh_grams"] = weigh.get("grams")
        attrs["weighed_grams"] = weigh.get("weighedG")
    return attrs


def _last_activity_attrs(c: ToqueCompanionCoordinator) -> dict[str, Any] | None:
    last = c.state.get("last")
    if not isinstance(last, dict):
        return None
    return {
        "kind": last.get("kind"),
        "outcome": last.get("outcome"),
        "summary": last.get("summary") or None,
        "recipe_id": last.get("recipeId") or None,
    }


SENSORS: tuple[ToqueCompanionSensorDescription, ...] = (
    ToqueCompanionSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=ROBOT_STATUSES,
        icon="mdi:pot-steam",
        value_fn=_derive_status,
    ),
    ToqueCompanionSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        needs_base_sample=True,
        value_fn=_temperature,
    ),
    ToqueCompanionSensorDescription(
        key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        needs_base_sample=True,
        value_fn=_target_temperature,
    ),
    ToqueCompanionSensorDescription(
        key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        needs_base_sample=True,
        value_fn=_weight,
    ),
    ToqueCompanionSensorDescription(
        key="speed_level",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        needs_base_sample=True,
        value_fn=_speed_level,
    ),
    ToqueCompanionSensorDescription(
        key="remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_remaining_seconds,
    ),
    ToqueCompanionSensorDescription(
        key="estimated_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.estimated_end_utc,
    ),
    ToqueCompanionSensorDescription(
        key="job_label",
        icon="mdi:stove",
        value_fn=lambda c: _truncate(dig(c.state, "job", "label")),
        attrs_fn=_job_attrs,
    ),
    ToqueCompanionSensorDescription(
        key="recipe",
        icon="mdi:chef-hat",
        value_fn=lambda c: _truncate(dig(c.state, "session", "title")),
        attrs_fn=_recipe_attrs,
    ),
    ToqueCompanionSensorDescription(
        key="step_number",
        icon="mdi:stairs",
        value_fn=_step_number,
    ),
    ToqueCompanionSensorDescription(
        key="current_step",
        icon="mdi:text-box-outline",
        value_fn=lambda c: _truncate((_current_step_obj(c) or {}).get("text")),
        attrs_fn=_step_attrs,
    ),
    ToqueCompanionSensorDescription(
        key="waiting_recipe",
        icon="mdi:book-clock-outline",
        value_fn=lambda c: _truncate(dig(c.state, "waiting", "title")),
    ),
    ToqueCompanionSensorDescription(
        key="last_activity",
        icon="mdi:history",
        value_fn=lambda c: _truncate(dig(c.state, "last", "title")),
        attrs_fn=_last_activity_attrs,
    ),
    ToqueCompanionSensorDescription(
        key="link_state",
        device_class=SensorDeviceClass.ENUM,
        options=LINK_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:connection",
        value_fn=_link_state,
        attrs_fn=lambda c: {"label": dig(c.state, "machine", "linkLabel") or None},
    ),
    ToqueCompanionSensorDescription(
        key="fault_message",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
        value_fn=lambda c: _truncate(dig(c.state, "machine", "faultMessage")),
        attrs_fn=lambda c: (
            {"code": dig(c.state, "machine", "faultCode")}
            if dig(c.state, "machine", "faultCode")
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToqueCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Toque Companion sensors."""
    coordinator = entry.runtime_data
    async_add_entities(ToqueCompanionSensor(coordinator, desc) for desc in SENSORS)


class ToqueCompanionSensor(ToqueCompanionEntity, SensorEntity):
    """Sensor entity backed by Toque Companion state."""

    entity_description: ToqueCompanionSensorDescription
    _unrecorded_attributes = frozenset({"text"})

    def __init__(
        self,
        coordinator: ToqueCompanionCoordinator,
        description: ToqueCompanionSensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            description.key,
            needs_base_sample=description.needs_base_sample,
        )
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator)
