"""Config flow for Toque Companion (6-digit code or QR pairing, reauth, reconfigure)."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CompanionApiError,
    CompanionError,
    CompanionProofError,
    CompanionUnsupportedProtocolError,
    ToqueCompanionClient,
    normalize_host,
    parse_pairing_qr,
)
from .const import (
    CONF_PAIRING_CODE,
    CONF_PHONE_ID,
    CONF_QR_TEXT,
    CONF_ROBOT_ID,
    CONF_TOKEN,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_PAIR_ERROR_MAP: dict[str, str] = {
    "wrong_code": "wrong_code",
    "code_dead": "code_dead",
    "code_expired": "code_expired",
    "pairing_closed": "pairing_closed",
    "too_many_phones": "too_many_phones",
}


class ToqueCompanionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle configuration, reauthentication, and reconfiguration for Toque Companion."""

    VERSION = 1

    async def _pair_and_verify(
        self,
        *,
        host: str,
        port: int,
        code: str,
        qr_text: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Pair with the robot using either a 6-digit code or a QR string and verify proof."""
        expected_robot_id: str | None = None
        secret: str | None = None

        if qr_text:
            payload = parse_pairing_qr(qr_text)
            if payload is None:
                raise _FlowError("invalid_qr")
            host = payload.host
            port = payload.port
            secret = payload.secret
            expected_robot_id = payload.robot_id
        else:
            if not host:
                raise _FlowError("invalid_host")
            try:
                host = normalize_host(host)
            except ValueError as err:
                raise _FlowError("invalid_host") from err
            cleaned_code = code.strip()
            if len(cleaned_code) != 6 or not cleaned_code.isdigit():
                raise _FlowError("invalid_code_format")
            code = cleaned_code

        client = ToqueCompanionClient(async_get_clientsession(self.hass), host, port)

        try:
            hello = await client.hello()
        except CompanionUnsupportedProtocolError as err:
            raise _FlowError("unsupported_protocol") from err
        except CompanionError as err:
            raise _FlowError("cannot_connect") from err

        if not hello.get("pairing"):
            raise _FlowError("pairing_closed")

        try:
            if secret is not None:
                pair_reply = await client.pair_with_secret(
                    secret, expected_robot_id=expected_robot_id
                )
            else:
                pair_reply = await client.pair_with_code(code)
            # Immediately verify HMAC proof and fetch initial state before persisting entry
            await client.get_state()
        except CompanionProofError as err:
            raise _FlowError("proof_failed") from err
        except CompanionApiError as err:
            mapped = _PAIR_ERROR_MAP.get(err.code, "cannot_connect")
            raise _FlowError(mapped) from err
        except CompanionError as err:
            raise _FlowError("cannot_connect") from err

        robot = pair_reply.get("robot") or {}
        phone = pair_reply.get("phone") or {}
        entry_data = {
            CONF_HOST: client.host,
            CONF_PORT: client.port,
            CONF_TOKEN: pair_reply["token"],
            CONF_PHONE_ID: phone["id"],
            CONF_ROBOT_ID: robot["id"],
        }
        return entry_data, robot

    # ------------------------------------------------------------------ user step

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            port = int(user_input.get(CONF_PORT) or DEFAULT_PORT)
            code = (user_input.get(CONF_PAIRING_CODE) or "").strip()
            qr_text = (user_input.get(CONF_QR_TEXT) or "").strip()

            if bool(code) == bool(qr_text):
                errors["base"] = "code_or_qr_required"
            else:
                try:
                    entry_data, robot = await self._pair_and_verify(
                        host=host, port=port, code=code, qr_text=qr_text
                    )
                except _FlowError as err:
                    errors["base"] = err.reason
                else:
                    await self.async_set_unique_id(entry_data[CONF_ROBOT_ID])
                    self._abort_if_unique_id_configured(updates=entry_data)
                    title = robot.get("name") or "Monsieur Cuisine"
                    return self.async_create_entry(title=title, data=entry_data)

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                    vol.Optional(
                        CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                    vol.Optional(CONF_PAIRING_CODE, default=""): str,
                    vol.Optional(CONF_QR_TEXT, default=""): str,
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------ reauth step

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = (user_input.get(CONF_HOST) or reauth_entry.data[CONF_HOST]).strip()
            port = int(user_input.get(CONF_PORT) or reauth_entry.data[CONF_PORT])
            code = (user_input.get(CONF_PAIRING_CODE) or "").strip()
            qr_text = (user_input.get(CONF_QR_TEXT) or "").strip()

            if bool(code) == bool(qr_text):
                errors["base"] = "code_or_qr_required"
            else:
                try:
                    new_data, _robot = await self._pair_and_verify(
                        host=host, port=port, code=code, qr_text=qr_text
                    )
                except _FlowError as err:
                    errors["base"] = err.reason
                else:
                    expected_id = reauth_entry.data.get(CONF_ROBOT_ID)
                    if expected_id and new_data[CONF_ROBOT_ID] != expected_id:
                        errors["base"] = "different_robot"
                    else:
                        return self.async_update_reload_and_abort(
                            reauth_entry, data_updates=new_data
                        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=reauth_entry.data[CONF_HOST]
                    ): str,
                    vol.Required(
                        CONF_PORT, default=reauth_entry.data[CONF_PORT]
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                    vol.Optional(CONF_PAIRING_CODE, default=""): str,
                    vol.Optional(CONF_QR_TEXT, default=""): str,
                }
            ),
            description_placeholders={"host": reauth_entry.data[CONF_HOST]},
            errors=errors,
        )

    # ------------------------------------------------------------------ reconfigure step

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update host/port if the robot IP changed, verifying proof before accepting."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            raw_host = (user_input.get(CONF_HOST) or "").strip()
            port = int(user_input.get(CONF_PORT) or DEFAULT_PORT)
            try:
                host = normalize_host(raw_host)
            except ValueError:
                errors["base"] = "invalid_host"
            else:
                client = ToqueCompanionClient(
                    async_get_clientsession(self.hass),
                    host,
                    port,
                    token=entry.data[CONF_TOKEN],
                    phone_id=entry.data[CONF_PHONE_ID],
                    robot_id=entry.data[CONF_ROBOT_ID],
                )
                try:
                    proven = await client.verify_robot()
                except CompanionError:
                    errors["base"] = "cannot_connect"
                else:
                    if not proven:
                        errors["base"] = "proof_failed"
                    else:
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={CONF_HOST: host, CONF_PORT: port},
                        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Required(
                        CONF_PORT, default=entry.data[CONF_PORT]
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                }
            ),
            errors=errors,
        )


class _FlowError(Exception):
    """Internal error mapping directly to config flow error keys."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
