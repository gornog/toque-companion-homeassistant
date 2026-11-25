"""Pure protocol tests for ToqueCompanionClient (no Home Assistant dependency)."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.toque_companion.api import (
    CompanionApiError,
    CompanionAuthError,
    CompanionProofError,
    CompanionUnsupportedProtocolError,
    ToqueCompanionClient,
    normalize_host,
    parse_pairing_qr,
)
from tests.fake_companion import FakeCompanionServer


@pytest.fixture
async def server():
    srv = FakeCompanionServer()
    await srv.start()
    try:
        yield srv
    finally:
        await srv.stop()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


def test_parse_pairing_qr_valid_and_invalid() -> None:
    qr = "toque://pair?v=1&h=192.168.3.140&p=8088&s=0123456789abcdef0123456789abcdef&r=a1b2c3d4e5f6&n=Mon%20Robot"
    parsed = parse_pairing_qr(qr)
    assert parsed is not None
    assert parsed.host == "192.168.3.140"
    assert parsed.port == 8088
    assert parsed.secret == "0123456789abcdef0123456789abcdef"
    assert parsed.robot_id == "a1b2c3d4e5f6"
    assert parsed.name == "Mon Robot"

    assert parse_pairing_qr("https://example.com") is None
    assert parse_pairing_qr("toque://pair?v=1&h=not-an-ip&p=8088&s=0123456789abcdef0123456789abcdef&r=a1b2c3d4e5f6") is None
    assert parse_pairing_qr("toque://pair?v=1&h=192.168.1.1&p=8088&s=short&r=a1b2c3d4e5f6") is None


def test_normalize_host_rejects_dns() -> None:
    assert normalize_host("192.168.3.140") == "192.168.3.140"
    assert normalize_host("localhost") == "127.0.0.1"
    with pytest.raises(ValueError):
        normalize_host("robot.local")


async def test_pair_with_code_prove_and_state(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    code, _ = server.open_pairing("123456")
    client = ToqueCompanionClient(session, server.host, server.port)

    hello = await client.hello()
    assert hello["service"] == "toque-companion"
    assert hello["pairing"] is True

    reply = await client.pair_with_code(code)
    assert len(reply["token"]) == 64
    assert client.phone_id == reply["phone"]["id"]
    assert client.robot_id == server.robot_id
    assert not client.is_proven

    # First authenticated call must prove robot first, then send bearer token
    state = await client.get_state()
    assert client.is_proven
    assert state["revision"] == 1
    assert state["robot"]["id"] == server.robot_id


async def test_pair_with_qr_and_mismatch(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    server.open_pairing()
    payload = parse_pairing_qr(server.qr_text())
    assert payload is not None

    client = ToqueCompanionClient(session, payload.host, payload.port)
    reply = await client.pair_with_secret(payload.secret, expected_robot_id=payload.robot_id)
    assert reply["phone"]["method"] == "qr"

    # Mismatched robot_id must reject and clear credentials
    server.open_pairing()
    payload2 = parse_pairing_qr(server.qr_text())
    assert payload2 is not None
    client2 = ToqueCompanionClient(session, payload2.host, payload2.port)
    with pytest.raises(CompanionProofError):
        await client2.pair_with_secret(payload2.secret, expected_robot_id="ffffffffffff")
    assert client2.token is None


async def test_pairing_error_cases(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    client = ToqueCompanionClient(session, server.host, server.port)

    # Closed pairing
    with pytest.raises(CompanionApiError) as err:
        await client.pair_with_code("111111")
    assert err.value.code == "pairing_closed"

    # Expired code
    server.open_pairing("222222")
    server.pairing_expired = True
    with pytest.raises(CompanionApiError) as err:
        await client.pair_with_code("222222")
    assert err.value.code == "code_expired"

    # 5 wrong attempts lock the code
    server.open_pairing("333333")
    for attempt in range(4):
        with pytest.raises(CompanionApiError) as err:
            await client.pair_with_code("000000")
        assert err.value.code == "wrong_code", f"attempt {attempt}"
    with pytest.raises(CompanionApiError) as err:
        await client.pair_with_code("000000")
    assert err.value.code == "code_dead"


async def test_false_proof_never_sends_bearer_token(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    token, phone_id = server.add_paired_client()
    server.corrupt_proof = True
    client = ToqueCompanionClient(
        session, server.host, server.port, token=token, phone_id=phone_id, robot_id=server.robot_id
    )

    with pytest.raises(CompanionProofError):
        await client.get_state()

    # Critical security guarantee: Authorization header was NEVER sent on any request
    assert server.seen_auth_headers == []
    assert not client.is_proven


async def test_long_poll_wakes_on_revision_change_and_handles_reset(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    token, phone_id = server.add_paired_client()
    client = ToqueCompanionClient(
        session, server.host, server.port, token=token, phone_id=phone_id, robot_id=server.robot_id
    )
    state1 = await client.get_state()
    assert state1["revision"] == 1

    async def _bump_soon() -> None:
        await asyncio.sleep(0.15)
        server.machine["weightG"] = 350
        server.bump_revision()

    bumper = asyncio.create_task(_bump_soon())
    state2 = await client.get_state(since=1, wait=5, replace=True)
    await bumper
    assert state2["revision"] == 2
    assert state2["machine"]["weightG"] == 350

    # Simulate robot restart where revision resets back to 1 (< since=2): must return immediately
    server.bump_revision(new_revision=1)
    state3 = await client.get_state(since=2, wait=5, replace=True)
    assert state3["revision"] == 1


async def test_actions_refusal_timeout_and_disallowed(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    token, phone_id = server.add_paired_client()
    client = ToqueCompanionClient(
        session, server.host, server.port, token=token, phone_id=phone_id, robot_id=server.robot_id
    )

    # Disallowed actions are blocked client-side before touching HTTP
    for forbidden in ("start", "resume", "adjust", "clear"):
        with pytest.raises(ValueError):
            await client.machine_action(forbidden)
    assert server.action_calls == []

    # Allowed tare succeeds
    res = await client.tare()
    assert res["ok"] is True
    assert server.machine["weightG"] == 0

    # Refused pause (409) does not retry
    with pytest.raises(CompanionApiError) as err:
        await client.pause()
    assert err.value.status == 409
    assert err.value.code == "nothing_running"

    # 504 no_answer raises without retrying
    server.action_calls.clear()
    server.action_override["stop"] = (504, "no_answer", "Pas de confirmation")
    with pytest.raises(CompanionApiError) as err:
        await client.stop()
    assert err.value.is_timeout_or_no_answer
    assert server.action_calls == ["stop"]


async def test_revoked_and_forget(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    token, phone_id = server.add_paired_client()
    client = ToqueCompanionClient(
        session, server.host, server.port, token=token, phone_id=phone_id, robot_id=server.robot_id
    )
    await client.get_state()
    assert client.is_proven

    # Remove phone on robot while client still has cached proof -> 401 unauthorized
    server.phones.pop(phone_id)
    with pytest.raises(CompanionAuthError) as err:
        await client.get_state()
    assert err.value.unauthorized
    assert not client.is_proven

    # Re-add and verify forget() removes phone cleanly
    token2, phone_id2 = server.add_paired_client()
    client2 = ToqueCompanionClient(
        session, server.host, server.port, token=token2, phone_id=phone_id2, robot_id=server.robot_id
    )
    await client2.forget()
    assert phone_id2 not in server.phones
    assert client2.token is None


async def test_unsupported_service(
    server: FakeCompanionServer, session: aiohttp.ClientSession
) -> None:
    server.service = "something-else"
    client = ToqueCompanionClient(session, server.host, server.port)
    with pytest.raises(CompanionUnsupportedProtocolError):
        await client.hello()
