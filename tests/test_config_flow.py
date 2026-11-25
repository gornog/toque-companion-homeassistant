"""Home Assistant config flow tests for Toque Companion."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.toque_companion.const import (
    CONF_PAIRING_CODE,
    CONF_PHONE_ID,
    CONF_QR_TEXT,
    CONF_ROBOT_ID,
    CONF_TOKEN,
    DOMAIN,
)
from tests.fake_companion import FakeCompanionServer


async def _noop_setup(*_args, **_kwargs) -> bool:
    return True


async def test_user_flow_pair_with_code(
    hass: HomeAssistant, fake_robot: FakeCompanionServer, monkeypatch
) -> None:
    monkeypatch.setattr("custom_components.toque_companion.async_setup_entry", _noop_setup)
    code, _ = fake_robot.open_pairing("654321")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: fake_robot.host,
            CONF_PORT: fake_robot.port,
            CONF_PAIRING_CODE: code,
            CONF_QR_TEXT: "",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == fake_robot.robot_name
    assert result["data"][CONF_HOST] == fake_robot.host
    assert result["data"][CONF_PORT] == fake_robot.port
    assert result["data"][CONF_ROBOT_ID] == fake_robot.robot_id
    assert len(result["data"][CONF_TOKEN]) == 64
    assert len(result["data"][CONF_PHONE_ID]) == 8


async def test_user_flow_pair_with_qr(
    hass: HomeAssistant, fake_robot: FakeCompanionServer, monkeypatch
) -> None:
    monkeypatch.setattr("custom_components.toque_companion.async_setup_entry", _noop_setup)
    fake_robot.open_pairing()
    qr = fake_robot.qr_text()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "", CONF_PORT: 8088, CONF_PAIRING_CODE: "", CONF_QR_TEXT: qr},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ROBOT_ID] == fake_robot.robot_id


async def test_user_flow_errors(
    hass: HomeAssistant, fake_robot: FakeCompanionServer, monkeypatch
) -> None:
    monkeypatch.setattr("custom_components.toque_companion.async_setup_entry", _noop_setup)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Neither code nor QR
    res_empty = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port, CONF_PAIRING_CODE: "", CONF_QR_TEXT: ""},
    )
    assert res_empty["errors"] == {"base": "code_or_qr_required"}

    # DNS hostname rejected
    res_dns = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "myrobot.local", CONF_PORT: fake_robot.port, CONF_PAIRING_CODE: "123456", CONF_QR_TEXT: ""},
    )
    assert res_dns["errors"] == {"base": "invalid_host"}

    # Pairing closed
    res_closed = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port, CONF_PAIRING_CODE: "123456", CONF_QR_TEXT: ""},
    )
    assert res_closed["errors"] == {"base": "pairing_closed"}

    # Wrong code
    fake_robot.open_pairing("999999")
    res_wrong = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port, CONF_PAIRING_CODE: "111111", CONF_QR_TEXT: ""},
    )
    assert res_wrong["errors"] == {"base": "wrong_code"}


async def test_reauth_and_reconfigure_flows(
    hass: HomeAssistant, fake_robot: FakeCompanionServer, monkeypatch
) -> None:
    monkeypatch.setattr("custom_components.toque_companion.async_setup_entry", _noop_setup)
    old_token, old_pid = fake_robot.add_paired_client()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=fake_robot.robot_id,
        data={
            CONF_HOST: fake_robot.host,
            CONF_PORT: fake_robot.port,
            CONF_TOKEN: old_token,
            CONF_PHONE_ID: old_pid,
            CONF_ROBOT_ID: fake_robot.robot_id,
        },
    )
    entry.add_to_hass(hass)

    # Reconfigure with failed proof must NOT accept new host
    fake_robot.corrupt_proof = True
    rec = await entry.start_reconfigure_flow(hass)
    rec = await hass.config_entries.flow.async_configure(
        rec["flow_id"], {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port}
    )
    assert rec["errors"] == {"base": "proof_failed"}
    fake_robot.corrupt_proof = False

    # Reconfigure with valid proof succeeds
    rec = await hass.config_entries.flow.async_configure(
        rec["flow_id"], {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port}
    )
    assert rec["type"] is FlowResultType.ABORT
    assert rec["reason"] == "reconfigure_successful"

    # Reauth with a fresh 6-digit code replaces token
    new_code, _ = fake_robot.open_pairing("777888")
    reauth = await entry.start_reauth_flow(hass)
    reauth = await hass.config_entries.flow.async_configure(
        reauth["flow_id"],
        {
            CONF_HOST: fake_robot.host,
            CONF_PORT: fake_robot.port,
            CONF_PAIRING_CODE: new_code,
            CONF_QR_TEXT: "",
        },
    )
    assert reauth["type"] is FlowResultType.ABORT
    assert reauth["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] != old_token
