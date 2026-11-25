"""Home Assistant integration tests for Toque Companion."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_HOST, CONF_PORT, STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.toque_companion.const import (
    CONF_PHONE_ID,
    CONF_ROBOT_ID,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.toque_companion.diagnostics import async_get_config_entry_diagnostics
from tests.fake_companion import FakeCompanionServer


async def _wait_for(predicate, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Condition not met within timeout")
        await asyncio.sleep(0.05)


async def _setup_entry(
    hass: HomeAssistant, fake_robot: FakeCompanionServer
) -> MockConfigEntry:
    token, phone_id = fake_robot.add_paired_client()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=fake_robot.robot_id,
        title=fake_robot.robot_name,
        data={
            CONF_HOST: fake_robot.host,
            CONF_PORT: fake_robot.port,
            CONF_TOKEN: token,
            CONF_PHONE_ID: phone_id,
            CONF_ROBOT_ID: fake_robot.robot_id,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_buttons_events_and_diagnostics(
    hass: HomeAssistant, fake_robot: FakeCompanionServer
) -> None:
    entry = await _setup_entry(hass, fake_robot)

    try:
        # Initial idle sensors and binary sensors
        assert hass.states.get("sensor.monsieur_cuisine_connect_status").state == "idle"
        assert hass.states.get("sensor.monsieur_cuisine_connect_temperature").state == "42"
        assert hass.states.get("sensor.monsieur_cuisine_connect_weight").state == "120"
        assert hass.states.get("binary_sensor.monsieur_cuisine_connect_bowl_present").state == STATE_ON
        assert hass.states.get("binary_sensor.monsieur_cuisine_connect_lid_open").state == STATE_OFF
        assert hass.states.get("binary_sensor.monsieur_cuisine_connect_fault").state == STATE_OFF

        # Buttons strictly follow state.can
        assert hass.states.get("button.monsieur_cuisine_connect_tare").state != STATE_UNAVAILABLE
        assert hass.states.get("button.monsieur_cuisine_connect_pause").state == STATE_UNAVAILABLE
        assert hass.states.get("button.monsieur_cuisine_connect_stop").state == STATE_UNAVAILABLE

        # Press tare button
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.monsieur_cuisine_connect_tare"},
            blocking=True,
        )
        await _wait_for(lambda: hass.states.get("sensor.monsieur_cuisine_connect_weight").state == "0")

        # Simulate active cooking job + journal alert
        fake_robot.job = {
            "kind": "MANUAL",
            "kindLabel": "Cuisson manuelle",
            "label": "Velouté",
            "state": "RUNNING",
            "counting": True,
            "endReason": "",
            "phaseIndex": 0,
            "phaseCount": 1,
            "elapsedMs": 10000,
            "totalMs": 60000,
            "remainingMs": 50000,
            "speed": 2,
            "tempLevel": 13,
            "tempC": 100,
            "reverse": False,
            "accessory": "BLADE",
            "hotBlendConfirmed": False,
            "startedAt": 1795340074000,
            "waitingStop": False,
            "pause": None,
        }
        fake_robot.machine["motorOn"] = True
        fake_robot.machine["heaterOn"] = True
        fake_robot.can["pause"] = {"allowed": True, "code": "", "reason": ""}
        fake_robot.can["stop"] = {"allowed": True, "code": "", "reason": ""}
        fake_robot.add_journal_entry(
            kind="temp_reached",
            alert="temp_reached",
            text="Température atteinte : 100 °C",
        )

        await _wait_for(lambda: hass.states.get("sensor.monsieur_cuisine_connect_status").state == "running")
        assert hass.states.get("button.monsieur_cuisine_connect_pause").state != STATE_UNAVAILABLE
        assert hass.states.get("button.monsieur_cuisine_connect_stop").state != STATE_UNAVAILABLE
        assert hass.states.get("sensor.monsieur_cuisine_connect_estimated_end").state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        )

        # Event entity received temp_reached alert
        await _wait_for(
            lambda: (
                (ev := hass.states.get("event.monsieur_cuisine_connect_cooking")) is not None
                and ev.attributes.get("event_type") == "temp_reached"
            )
        )

        # Press pause button -> status becomes paused, pause button becomes unavailable
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.monsieur_cuisine_connect_pause"},
            blocking=True,
        )
        await _wait_for(lambda: hass.states.get("sensor.monsieur_cuisine_connect_status").state == "paused")
        assert hass.states.get("button.monsieur_cuisine_connect_pause").state == STATE_UNAVAILABLE
        assert hass.states.get("sensor.monsieur_cuisine_connect_estimated_end").state == STATE_UNKNOWN

        # 504 no_answer raises HomeAssistantError without retrying
        fake_robot.action_calls.clear()
        fake_robot.action_override["stop"] = (504, "no_answer", "Pas de confirmation")
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.monsieur_cuisine_connect_stop"},
                blocking=True,
            )
        assert fake_robot.action_calls == ["stop"]
        fake_robot.action_override.clear()

        # Unknown temperature when tempKnown=False (Smart outside heating)
        fake_robot.machine["tempKnown"] = False
        fake_robot.bump_revision()
        await _wait_for(
            lambda: hass.states.get("sensor.monsieur_cuisine_connect_temperature").state == STATE_UNKNOWN
        )

        # Diagnostics strictly redacts token, phone_id, and host
        diag = await async_get_config_entry_diagnostics(hass, entry)
        diag_str = str(diag)
        assert entry.data[CONF_TOKEN] not in diag_str
        assert entry.data[CONF_PHONE_ID] not in diag_str
        assert entry.data[CONF_HOST] not in diag_str

        # Single long-poll discipline
        assert fake_robot.max_concurrent_long_polls <= 1
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_disconnect_marks_unavailable_and_reauth_on_revoke(
    hass: HomeAssistant, fake_robot: FakeCompanionServer
) -> None:
    entry = await _setup_entry(hass, fake_robot)
    try:
        # Revoking token on robot triggers 401 -> unavailable + reauth flow
        fake_robot.phones.clear()
        fake_robot.bump_revision()

        await _wait_for(
            lambda: hass.states.get("sensor.monsieur_cuisine_connect_status").state == STATE_UNAVAILABLE
        )
        flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert any(f["context"].get("source") == "reauth" for f in flows)
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
