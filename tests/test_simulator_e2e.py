"""End-to-end tests against the official Toque v0.10.0 JVM PC Companion simulator.

Runs strictly against loopback (127.0.0.1:18088 / 127.0.0.1:18089), never touching any physical robot.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import aiohttp
import pytest

from custom_components.toque_companion.api import (
    CompanionApiError,
    CompanionProofError,
    ToqueCompanionClient,
    parse_pairing_qr,
)

WORKSPACE = Path(__file__).resolve().parents[2]
TOQUE_V0100 = WORKSPACE / "toque-v0100"
JDK_HOME = WORKSPACE / "diagnostics" / "jdk" / "jdk-21.0.13+9"
GRADLE_USER = WORKSPACE / "diagnostics" / "gradle-user"

DEMO_PORT = 18088
CTRL_PORT = DEMO_PORT + 1


def _find_kotlin_stdlib() -> Path | None:
    if not GRADLE_USER.is_dir():
        return None
    matches = sorted(GRADLE_USER.rglob("kotlin-stdlib-*.jar"))
    matches = [m for m in matches if "sources" not in m.name and "jdk" not in m.name]
    return matches[-1] if matches else None


def _simulator_available() -> bool:
    return (
        (TOQUE_V0100 / "core" / "build" / "classes" / "kotlin" / "main").is_dir()
        and (TOQUE_V0100 / "core" / "build" / "classes" / "kotlin" / "demo").is_dir()
        and (JDK_HOME / "bin" / "java.exe").is_file()
        and _find_kotlin_stdlib() is not None
    )


async def _demo_cmd(session: aiohttp.ClientSession, cmd: str) -> str:
    async with session.post(
        f"http://127.0.0.1:{CTRL_PORT}/demo",
        data=cmd.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        assert resp.status == 200
        return (await resp.text()).strip()


@pytest.mark.simulator
@pytest.mark.skipif(not _simulator_available(), reason="Official v0.10.0 simulator classes not built")
async def test_official_v0100_simulator_end_to_end() -> None:
    """Validate pairing, HMAC proof, long-poll, pause/stop/tare, recipe session, journal, and unpair against real v0.10.0 JVM simulator."""
    stdlib = _find_kotlin_stdlib()
    assert stdlib is not None
    cp = os.pathsep.join(
        [
            str(TOQUE_V0100 / "core" / "build" / "classes" / "kotlin" / "demo"),
            str(TOQUE_V0100 / "core" / "build" / "classes" / "kotlin" / "main"),
            str(stdlib),
        ]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "store.json"
        proc = subprocess.Popen(
            [
                str(JDK_HOME / "bin" / "java.exe"),
                "-cp",
                cp,
                "app.toque.core.companion.demo.DemoMainKt",
                "--port",
                str(DEMO_PORT),
                "--fast",
                "5",
                "--store",
                str(store_path),
            ],
            cwd=str(TOQUE_V0100 / "core"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            async with aiohttp.ClientSession() as session:
                # Wait for simulator HTTP server to come up
                deadline = time.monotonic() + 20.0
                while True:
                    try:
                        async with session.get(
                            f"http://127.0.0.1:{DEMO_PORT}/api/hello",
                            timeout=aiohttp.ClientTimeout(total=2),
                        ) as r:
                            if r.status == 200:
                                break
                    except Exception:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError("Toque v0.10.0 simulator failed to start in time")
                    await asyncio.sleep(0.25)

                # 1. Open pairing and pair client #1 via 6-digit code
                pair_out = await _demo_cmd(session, "pair")
                m_code = re.search(r"code\s+(\d{6})", pair_out)
                assert m_code is not None, f"Unexpected pair output: {pair_out}"
                code = m_code.group(1)

                client1 = ToqueCompanionClient(session, "127.0.0.1", DEMO_PORT)
                hello = await client1.hello()
                assert hello["service"] == "toque-companion"
                assert hello["protocol"] == 1
                assert hello["pairing"] is True

                pair_reply = await client1.pair_with_code(code)
                assert len(pair_reply["token"]) == 64
                assert pair_reply["phone"]["method"] == "code"

                # 2. Real HMAC-SHA256 proof + /api/robot + /api/state
                assert await client1.verify_robot() is True
                who = await client1.get_robot()
                assert who["robot"]["id"] == client1.robot_id

                # Wait briefly for SimBoard link to reach READY
                state = await client1.get_state()
                for _ in range(20):
                    if state["machine"]["link"] == "READY" and state["machine"]["hasSample"]:
                        break
                    await asyncio.sleep(0.2)
                    state = await client1.get_state()
                assert state["machine"]["link"] == "READY"
                assert state["can"]["tare"]["allowed"] is True
                assert state["can"]["pause"]["allowed"] is False

                # 3. Pair client #2 via QR string to verify multi-client + QR parsing
                pair_out2 = await _demo_cmd(session, "pair")
                m_qr = re.search(r"(toque://pair\?\S+)", pair_out2)
                assert m_qr is not None, f"Unexpected QR output: {pair_out2}"
                qr_payload = parse_pairing_qr(m_qr.group(1))
                assert qr_payload is not None
                client2 = ToqueCompanionClient(session, qr_payload.host, qr_payload.port)
                await client2.pair_with_secret(
                    qr_payload.secret, expected_robot_id=qr_payload.robot_id
                )
                assert await client2.verify_robot() is True

                # 4. Long-poll wakes up immediately when weight changes, then tare zeros it
                rev = state["revision"]

                async def _put_weight() -> None:
                    await asyncio.sleep(0.25)
                    await _demo_cmd(session, "weight 420")

                t = asyncio.create_task(_put_weight())
                state_w = await client1.get_state(since=rev, wait=5, replace=True)
                await t
                assert state_w["revision"] > rev

                # Poll briefly until weight reading stabilizes at 420
                for _ in range(15):
                    if state_w["machine"]["weightG"] == 420:
                        break
                    await asyncio.sleep(0.15)
                    state_w = await client1.get_state()
                assert state_w["machine"]["weightG"] == 420

                tare_res = await client1.tare()
                assert tare_res["ok"] is True
                for _ in range(15):
                    state_t = await client1.get_state()
                    if state_t["machine"]["weightG"] == 0:
                        break
                    await asyncio.sleep(0.15)
                assert state_t["machine"]["weightG"] == 0

                # 5. Start manual job on simulator -> pause -> verify -> stop -> verify 409 refusal
                start_out = await _demo_cmd(session, "manual 2 80 120")
                assert "ok" in start_out.lower(), start_out
                for _ in range(20):
                    st_run = await client1.get_state()
                    if (st_run.get("job") or {}).get("state") == "RUNNING":
                        break
                    await asyncio.sleep(0.15)
                assert st_run["job"]["state"] == "RUNNING"
                assert st_run["can"]["pause"]["allowed"] is True
                assert st_run["can"]["stop"]["allowed"] is True

                pause_res = await client1.pause()
                assert pause_res["ok"] is True
                for _ in range(20):
                    st_paused = await client1.get_state()
                    if (st_paused.get("job") or {}).get("state") == "PAUSED":
                        break
                    await asyncio.sleep(0.15)
                assert st_paused["job"]["state"] == "PAUSED"
                assert st_paused["can"]["pause"]["allowed"] is False
                assert st_paused["can"]["stop"]["allowed"] is True

                stop_res = await client1.stop()
                assert stop_res["ok"] is True
                for _ in range(20):
                    st_stopped = await client1.get_state()
                    if (st_stopped.get("job") or {}).get("state") in ("ABORTED", "FINISHED"):
                        break
                    await asyncio.sleep(0.15)
                assert st_stopped["job"]["state"] == "ABORTED"
                assert st_stopped["can"]["stop"]["allowed"] is False

                # Refusal check when nothing running
                with pytest.raises(CompanionApiError) as err:
                    await client1.pause()
                assert err.value.status == 409

                # 6. Lid / bowl simulation + guided recipe session + journal
                await _demo_cmd(session, "lid open")
                for _ in range(15):
                    st_lid = await client1.get_state()
                    if st_lid["machine"]["lidOpen"] is True:
                        break
                    await asyncio.sleep(0.15)
                assert st_lid["machine"]["lidOpen"] is True
                await _demo_cmd(session, "lid close")

                launch_out = await _demo_cmd(session, "launch")
                assert "recette lancée" in launch_out.lower()
                st_rec = await client1.get_state()
                assert st_rec["session"] is not None
                assert st_rec["session"]["stepCount"] > 0

                journal = await client1.get_journal(after=0, limit=50)
                assert journal["lastSeq"] > 0
                assert len(journal["entries"]) > 0

                # 7. Unpair client #2 via forget() and verify proof now fails (decoy key)
                await client2.forget()
                assert client2.token is None

                # Revoking client #1 on robot makes verify_robot return False (decoy proof)
                await _demo_cmd(session, "unpair all")
                client1.invalidate_proof()
                with pytest.raises(CompanionProofError):
                    await client1.get_state()

                await _demo_cmd(session, "quit")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
