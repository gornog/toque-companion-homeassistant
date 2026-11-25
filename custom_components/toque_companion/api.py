"""Async client for the official Toque Companion v1 local HTTP API.

Protocol verified against Wuki60/MrCuisineVibeConnect tag v0.10.0
(commit b2bfe1ceac95bac890912237bbe58ade68a3bfeb):
  - core/src/main/kotlin/app/toque/core/companion/CompanionApi.kt
  - core/src/main/kotlin/app/toque/core/companion/CompanionProof.kt
  - core/src/main/kotlin/app/toque/core/companion/Pairing.kt
  - core/src/main/kotlin/app/toque/core/companion/PairingPayload.kt
  - core/src/main/kotlin/app/toque/core/companion/client/CompanionClient.kt

Security model:
  - The robot serves plain HTTP on the local network (default port 8088).
  - Before sending the bearer token to any address (initially, after any
    network/protocol error, or after host/port changes), the client performs
    the HMAC-SHA256 proof exchange (POST /api/prove) and verifies the proof
    in constant time. If proof fails, the bearer token is NEVER transmitted.
  - Only read endpoints, pairing/unpairing, and the safe machine actions
    (pause, stop, tare) are exposed by this client.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
from typing import Any
from urllib.parse import parse_qsl

import aiohttp

from .const import (
    ALLOWED_ACTIONS,
    COMMAND_TIMEOUT_S,
    HTTP_CONNECT_TIMEOUT_S,
    HTTP_READ_TIMEOUT_S,
    LONG_POLL_WAIT_S,
    SERVICE_NAME,
    SUPPORTED_PROTOCOL,
)

_HEX_RE = re.compile(r"^[0-9a-f]+$")
_QR_PREFIX = "toque://pair?"
_QR_MAX_LENGTH = 200
_QR_MAX_NAME = 32
_SECRET_HEX_LEN = 32
_ROBOT_ID_HEX_LEN = 12
_PHONE_ID_HEX_LEN = 8
_NONCE_HEX_LEN = 32


class CompanionError(Exception):
    """Base error for the Toque Companion API client."""


class CompanionConnectionError(CompanionError):
    """Network, timeout, or malformed-response error talking to the robot."""


class CompanionApiError(CompanionError):
    """Structured HTTP error response from the robot ({"error": {"code", "message"}})."""

    def __init__(self, status: int, code: str, message: str = "") -> None:
        self.status = status
        self.code = code
        self.message = message
        detail = f"HTTP {status} {code}: {message}" if message else f"HTTP {status} {code}"
        super().__init__(detail)

    @property
    def unauthorized(self) -> bool:
        return self.status == 401

    @property
    def is_timeout_or_no_answer(self) -> bool:
        return self.status == 504 and self.code in ("timeout", "no_answer")


class CompanionAuthError(CompanionApiError):
    """Bearer token rejected (401 unauthorized)."""


class CompanionProofError(CompanionError):
    """Robot failed the HMAC-SHA256 identity proof; bearer token was NOT sent."""


class CompanionUnsupportedProtocolError(CompanionError):
    """Target is not a supported Toque Companion service."""


@dataclass(frozen=True)
class PairingPayload:
    """Parsed Toque pairing QR code payload (toque://pair?... )."""

    host: str
    port: int
    secret: str
    robot_id: str
    name: str
    version: int = SUPPORTED_PROTOCOL


def parse_pairing_qr(text: str) -> PairingPayload | None:
    """Parse a Toque pairing QR string identically to PairingPayload.parse()."""
    trimmed = text.strip()
    if len(trimmed) > _QR_MAX_LENGTH or not trimmed.startswith(_QR_PREFIX):
        return None
    raw_query = trimmed[len(_QR_PREFIX) :]
    params: dict[str, str] = {}
    for key, value in parse_qsl(raw_query, keep_blank_values=True, strict_parsing=False):
        if key not in params:
            params[key] = value

    try:
        version = int(params["v"])
        port = int(params["p"])
    except (KeyError, ValueError):
        return None

    if version < 1 or not (1 <= port <= 65535):
        return None

    host = params.get("h", "")
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        return None

    secret = params.get("s", "")
    if len(secret) != _SECRET_HEX_LEN or not _HEX_RE.match(secret):
        return None

    robot_id = params.get("r", "")
    if len(robot_id) != _ROBOT_ID_HEX_LEN or not _HEX_RE.match(robot_id):
        return None

    name = params.get("n", "")[:_QR_MAX_NAME]
    return PairingPayload(
        host=host,
        port=port,
        secret=secret,
        robot_id=robot_id,
        name=name,
        version=version,
    )


def normalize_host(host: str) -> str:
    """Validate and normalize host to an IP literal or 'localhost'.

    Toque Companion enforces Host-header DNS-rebinding defence (421 bad_host)
    and computes proof against the dialled IPv4 literal.
    """
    cleaned = host.strip()
    if cleaned.lower() == "localhost":
        return "127.0.0.1"
    # Strip optional IPv6 brackets
    bare = cleaned[1:-1] if cleaned.startswith("[") and cleaned.endswith("]") else cleaned
    try:
        addr = ipaddress.ip_address(bare)
    except ValueError as err:
        raise ValueError("Host must be an IP address or localhost") from err
    return str(addr)


def sha256_hex(text: str) -> str:
    """Lowercase hex SHA-256 of UTF-8 text (matches PairingManager.sha256Hex)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_proof(token_sha256_hex: str, nonce: str, robot_id: str, address: str) -> str:
    """Compute expected HMAC-SHA256 proof (matches CompanionProof.compute)."""
    key = token_sha256_hex.encode("utf-8")
    message = f"toque-prove-1|{nonce}|{robot_id}|{address}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_proof(token: str, nonce: str, robot_id: str, address: str, proof: str) -> bool:
    """Constant-time verification of a robot proof (matches CompanionProof.check)."""
    if not isinstance(proof, str) or len(proof) != 64:
        return False
    expected = compute_proof(sha256_hex(token), nonce, robot_id, address)
    return hmac.compare_digest(expected, proof)


class ToqueCompanionClient:
    """Async HTTP client for the official Toque Companion v1 API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = 8088,
        token: str | None = None,
        phone_id: str | None = None,
        robot_id: str | None = None,
        *,
        connect_timeout: float = HTTP_CONNECT_TIMEOUT_S,
        read_timeout: float = HTTP_READ_TIMEOUT_S,
    ) -> None:
        self._session = session
        self._host = normalize_host(host)
        self._port = int(port)
        self._token = token
        self._phone_id = phone_id
        self._robot_id = robot_id
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._proven_target: str | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def phone_id(self) -> str | None:
        return self._phone_id

    @property
    def robot_id(self) -> str | None:
        return self._robot_id

    @property
    def is_proven(self) -> bool:
        return self._proven_target == self._target_key

    @property
    def _target_key(self) -> str:
        return f"{self._host}:{self._port}"

    @property
    def base_url(self) -> str:
        url_host = f"[{self._host}]" if ":" in self._host else self._host
        return f"http://{url_host}:{self._port}"

    def invalidate_proof(self) -> None:
        """Force re-verification via POST /api/prove before the next auth call."""
        self._proven_target = None

    def set_credentials(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        phone_id: str | None = None,
        robot_id: str | None = None,
    ) -> None:
        """Update endpoint or credentials and invalidate cached proof."""
        if host is not None:
            self._host = normalize_host(host)
        if port is not None:
            self._port = int(port)
        if token is not None:
            self._token = token
        if phone_id is not None:
            self._phone_id = phone_id
        if robot_id is not None:
            self._robot_id = robot_id
        self._proven_target = None

    # ------------------------------------------------------------------ unauthenticated

    async def hello(self) -> dict[str, Any]:
        """GET /api/hello — identify a Toque Companion server and pairing state."""
        data = await self._request("GET", "/api/hello", auth=False)
        if data.get("service") != SERVICE_NAME:
            raise CompanionUnsupportedProtocolError(
                f"Unexpected service: {data.get('service')!r}"
            )
        protocol = data.get("protocol")
        if not isinstance(protocol, int) or protocol < SUPPORTED_PROTOCOL:
            raise CompanionUnsupportedProtocolError(
                f"Unsupported protocol version: {protocol!r}"
            )
        return data

    async def pair_with_code(self, code: str) -> dict[str, Any]:
        """POST /api/pair using the 6-digit code shown on the robot."""
        cleaned = code.strip()
        return await self._pair({"code": cleaned})

    async def pair_with_secret(
        self, secret: str, *, expected_robot_id: str | None = None
    ) -> dict[str, Any]:
        """POST /api/pair using the one-time QR secret, verifying robot.id if given."""
        reply = await self._pair({"secret": secret.strip()})
        actual_robot_id = (reply.get("robot") or {}).get("id")
        if expected_robot_id is not None and actual_robot_id != expected_robot_id:
            self._token = None
            self._phone_id = None
            self._robot_id = None
            self._proven_target = None
            raise CompanionProofError(
                f"Robot ID mismatch during QR pairing: expected {expected_robot_id}, got {actual_robot_id}"
            )
        return reply

    async def _pair(self, payload: dict[str, Any]) -> dict[str, Any]:
        reply = await self._request("POST", "/api/pair", body=payload, auth=False)
        token = reply.get("token")
        phone_id = (reply.get("phone") or {}).get("id")
        robot_id = (reply.get("robot") or {}).get("id")
        if not isinstance(token, str) or not isinstance(phone_id, str) or not isinstance(robot_id, str):
            raise CompanionConnectionError("Malformed /api/pair response")
        self._token = token
        self._phone_id = phone_id
        self._robot_id = robot_id
        self._proven_target = None
        return reply

    async def verify_robot(self) -> bool:
        """POST /api/prove — prove this address is our robot without sending the token."""
        if not self._token or not self._phone_id or not self._robot_id:
            return False
        if len(self._phone_id) != _PHONE_ID_HEX_LEN or not _HEX_RE.match(self._phone_id):
            return False

        nonce = secrets.token_hex(_NONCE_HEX_LEN // 2)
        try:
            reply = await self._request(
                "POST",
                "/api/prove",
                body={"phoneId": self._phone_id, "nonce": nonce},
                auth=False,
            )
        except CompanionApiError:
            return False

        proof = reply.get("proof", "")
        ok = verify_proof(self._token, nonce, self._robot_id, self._host, proof)
        if ok:
            self._proven_target = self._target_key
        else:
            self._proven_target = None
        return ok

    async def _ensure_proven(self) -> None:
        if self._proven_target == self._target_key:
            return
        if not await self.verify_robot():
            raise CompanionProofError(
                f"Robot at {self._host}:{self._port} did not prove identity"
            )

    # ------------------------------------------------------------------ authenticated reads

    async def get_robot(self) -> dict[str, Any]:
        """GET /api/robot — robot metadata and this paired client record."""
        return await self._request("GET", "/api/robot")

    async def get_state(
        self,
        *,
        since: int | None = None,
        wait: int = LONG_POLL_WAIT_S,
        quiet: bool = False,
        replace: bool = False,
    ) -> dict[str, Any]:
        """GET /api/state — immediate state or bounded long-poll."""
        params: dict[str, str] = {}
        timeout = self._read_timeout
        if since is not None:
            clamped_wait = max(0, min(120, int(wait)))
            params["since"] = str(int(since))
            params["wait"] = str(clamped_wait)
            if quiet:
                params["quiet"] = "1"
            if replace:
                params["replace"] = "1"
            timeout = self._read_timeout + clamped_wait
        return await self._request(
            "GET", "/api/state", params=params or None, read_timeout=timeout
        )

    async def get_journal(self, *, after: int = 0, limit: int = 100) -> dict[str, Any]:
        """GET /api/journal — activity journal entries newer than `after`."""
        params = {
            "after": str(max(0, int(after))),
            "limit": str(max(1, min(300, int(limit)))),
        }
        return await self._request("GET", "/api/journal", params=params)

    # ------------------------------------------------------------------ safe controls only

    async def machine_action(self, action: str) -> dict[str, Any]:
        """Execute a safe machine action: strictly pause, stop, or tare.

        Never retries automatically: a 504 no_answer or timeout may mean the
        robot already applied the command.
        """
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported or disallowed action: {action!r}")
        return await self._request(
            "POST",
            f"/api/machine/{action}",
            body=None,
            read_timeout=COMMAND_TIMEOUT_S,
        )

    async def pause(self) -> dict[str, Any]:
        """POST /api/machine/pause."""
        return await self.machine_action("pause")

    async def stop(self) -> dict[str, Any]:
        """POST /api/machine/stop."""
        return await self.machine_action("stop")

    async def tare(self) -> dict[str, Any]:
        """POST /api/machine/tare."""
        return await self.machine_action("tare")

    async def forget(self) -> dict[str, Any]:
        """DELETE /api/phones/me — remove this client from the robot."""
        try:
            return await self._request(
                "DELETE", "/api/phones/me", read_timeout=self._read_timeout
            )
        finally:
            self._token = None
            self._proven_target = None

    # ------------------------------------------------------------------ HTTP transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        auth: bool = True,
        read_timeout: float | None = None,
    ) -> dict[str, Any]:
        if auth:
            await self._ensure_proven()
            if not self._token:
                raise CompanionAuthError(401, "unauthorized", "No bearer token")

        headers: dict[str, str] = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"

        kwargs: dict[str, Any] = {
            "headers": headers,
            "params": params,
            "allow_redirects": False,
            "timeout": aiohttp.ClientTimeout(
                total=None,
                connect=self._connect_timeout,
                sock_connect=self._connect_timeout,
                sock_read=read_timeout if read_timeout is not None else self._read_timeout,
            ),
        }
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            kwargs["json"] = body
        elif method == "POST":
            headers["Content-Type"] = "application/json; charset=utf-8"
            kwargs["data"] = b""

        url = f"{self.base_url}{path}"
        try:
            async with self._session.request(method, url, **kwargs) as resp:
                raw_text = await resp.text(encoding="utf-8", errors="replace")
                status = resp.status
        except asyncio.CancelledError:
            # Cut request invalidates proof, matching CompanionClient.cancelAll()
            self._proven_target = None
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            self._proven_target = None
            raise CompanionConnectionError(
                f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
            ) from err

        if status >= 400:
            code = f"http_{status}"
            message = ""
            try:
                err_payload = json.loads(raw_text) if raw_text else {}
                if isinstance(err_payload, dict) and isinstance(err_payload.get("error"), dict):
                    code = str(err_payload["error"].get("code") or code)
                    message = str(err_payload["error"].get("message") or "")
            except Exception:
                pass
            if status == 401:
                self._proven_target = None
                raise CompanionAuthError(status, code, message)
            raise CompanionApiError(status, code, message)

        try:
            parsed = json.loads(raw_text)
        except Exception as err:
            self._proven_target = None
            raise CompanionConnectionError(f"Invalid JSON response: {err}") from err

        if not isinstance(parsed, dict):
            self._proven_target = None
            raise CompanionConnectionError("Expected JSON object response")

        return parsed
