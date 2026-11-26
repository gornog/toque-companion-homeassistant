"""Home Assistant config flow tests for Toque Companion."""

from __future__ import annotations

from ipaddress import ip_address
import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.toque_companion.const import (
    CONF_PAIRING_CODE,
    CONF_PHONE_ID,
    CONF_QR_TEXT,
    CONF_ROBOT_ID,
    CONF_SENSOR_ONLY,
    CONF_TOKEN,
    DOMAIN,
)
from tests.fake_companion import FakeCompanionServer


async def _noop_setup(*_args, **_kwargs) -> bool:
    return True


def _zeroconf_info(
    host: str,
    port: int,
    robot_id: str,
    *,
    version: str = "1",
    model: str = "mc-connect",
    name: str = "Toque Monsieur Cuisine Connect._toque._tcp.local.",
) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        hostname="toque.local.",
        name=name,
        port=port,
        type="_toque._tcp.local.",
        properties={"id": robot_id, "v": version, "model": model},
    )


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
            CONF_SENSOR_ONLY: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == fake_robot.robot_name
    assert result["data"][CONF_HOST] == fake_robot.host
    assert result["data"][CONF_PORT] == fake_robot.port
    assert result["data"][CONF_ROBOT_ID] == fake_robot.robot_id
    assert result["data"][CONF_SENSOR_ONLY] is True
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
    assert result["data"][CONF_SENSOR_ONLY] is False


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
            CONF_HOST: "127.0.0.2",
            CONF_PORT: fake_robot.port,
            CONF_TOKEN: old_token,
            CONF_PHONE_ID: old_pid,
            CONF_ROBOT_ID: fake_robot.robot_id,
            CONF_SENSOR_ONLY: False,
        },
    )
    entry.add_to_hass(hass)

    # Reconfigure with changed address + failed proof must NOT accept new host
    fake_robot.corrupt_proof = True
    rec = await entry.start_reconfigure_flow(hass)
    rec = await hass.config_entries.flow.async_configure(
        rec["flow_id"],
        {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port, CONF_SENSOR_ONLY: False},
    )
    assert rec["errors"] == {"base": "proof_failed"}
    fake_robot.corrupt_proof = False

    # Reconfigure with changed address + valid proof succeeds
    rec = await hass.config_entries.flow.async_configure(
        rec["flow_id"],
        {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port, CONF_SENSOR_ONLY: False},
    )
    assert rec["type"] is FlowResultType.ABORT
    assert rec["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == fake_robot.host

    # Reconfigure toggling sensor_only on same address succeeds without re-proving
    fake_robot.corrupt_proof = True
    rec2 = await entry.start_reconfigure_flow(hass)
    rec2 = await hass.config_entries.flow.async_configure(
        rec2["flow_id"],
        {CONF_HOST: fake_robot.host, CONF_PORT: fake_robot.port, CONF_SENSOR_ONLY: True},
    )
    assert rec2["type"] is FlowResultType.ABORT
    assert rec2["reason"] == "reconfigure_successful"
    assert entry.data[CONF_SENSOR_ONLY] is True
    fake_robot.corrupt_proof = False

    # Reauth with a fresh 6-digit code replaces token and preserves/sets sensor_only
    new_code, _ = fake_robot.open_pairing("777888")
    reauth = await entry.start_reauth_flow(hass)
    reauth = await hass.config_entries.flow.async_configure(
        reauth["flow_id"],
        {
            CONF_HOST: fake_robot.host,
            CONF_PORT: fake_robot.port,
            CONF_PAIRING_CODE: new_code,
            CONF_QR_TEXT: "",
            CONF_SENSOR_ONLY: False,
        },
    )
    assert reauth["type"] is FlowResultType.ABORT
    assert reauth["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] != old_token
    assert entry.data[CONF_SENSOR_ONLY] is False


async def test_zeroconf_discovery_new_robot(
    hass: HomeAssistant, fake_robot: FakeCompanionServer, monkeypatch
) -> None:
    monkeypatch.setattr("custom_components.toque_companion.async_setup_entry", _noop_setup)
    code, _ = fake_robot.open_pairing("246810")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf_info(fake_robot.host, fake_robot.port, fake_robot.robot_id),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"

    done = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PAIRING_CODE: code, CONF_SENSOR_ONLY: True},
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"][CONF_HOST] == fake_robot.host
    assert done["data"][CONF_PORT] == fake_robot.port
    assert done["data"][CONF_ROBOT_ID] == fake_robot.robot_id
    assert done["data"][CONF_SENSOR_ONLY] is True


async def test_zeroconf_ignores_non_companion_service(
    hass: HomeAssistant, fake_robot: FakeCompanionServer
) -> None:
    fake_robot.service = "other-toque-fork"
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf_info(fake_robot.host, fake_robot.port, fake_robot.robot_id),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unsupported_protocol"


async def test_zeroconf_updates_ip_only_after_proof(
    hass: HomeAssistant, fake_robot: FakeCompanionServer, monkeypatch
) -> None:
    monkeypatch.setattr("custom_components.toque_companion.async_setup_entry", _noop_setup)
    token, phone_id = fake_robot.add_paired_client()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=fake_robot.robot_id,
        data={
            CONF_HOST: "127.0.0.2",
            CONF_PORT: fake_robot.port,
            CONF_TOKEN: token,
            CONF_PHONE_ID: phone_id,
            CONF_ROBOT_ID: fake_robot.robot_id,
            CONF_SENSOR_ONLY: False,
        },
    )
    entry.add_to_hass(hass)

    # Failed proof must NOT overwrite existing host
    fake_robot.corrupt_proof = True
    res_bad = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf_info(fake_robot.host, fake_robot.port, fake_robot.robot_id),
    )
    assert res_bad["type"] is FlowResultType.ABORT
    assert res_bad["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "127.0.0.2"

    # Valid proof updates host safely
    fake_robot.corrupt_proof = False
    res_ok = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf_info(fake_robot.host, fake_robot.port, fake_robot.robot_id),
    )
    assert res_ok["type"] is FlowResultType.ABORT
    assert res_ok["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == fake_robot.host
