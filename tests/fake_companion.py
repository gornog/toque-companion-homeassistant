"""Faithful local aiohttp fake Toque Companion v1 server for deterministic tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hmac
import secrets
import time
from typing import Any

from aiohttp import web

from custom_components.toque_companion.api import compute_proof, sha256_hex


@dataclass
class PairedClient:
    id: str
    number: int
    token_hash: str
    method: str = "code"
    paired_at: int = 1795340000000
    last_seen_at: int = 1795340000000


@dataclass
class FakeCompanionServer:
    """In-memory Toque Companion v1 HTTP server implementing pairing, proof, long-poll, journal, and actions."""

    robot_id: str = "a1b2c3d4e5f6"
    robot_name: str = "Monsieur Cuisine Connect"
    app_version: str = "0.10.0"
    model: str = "mc-connect"
    protocol: int = 1
    service: str = "toque-companion"

    # Pairing state
    pairing_code: str | None = None
    pairing_secret: str | None = None
    pairing_expired: bool = False
    pairing_failures: int = 0
    pairing_dead: bool = False
    max_phones: int = 8

    # Proof / fault injection
    corrupt_proof: bool = False
    action_override: dict[str, tuple[int, str, str]] = field(default_factory=dict)

    # Recorded telemetry for assertions
    seen_auth_headers: list[tuple[str, str, str | None]] = field(default_factory=list)
    action_calls: list[str] = field(default_factory=list)
    active_long_polls: int = 0
    max_concurrent_long_polls: int = 0

    def __post_init__(self) -> None:
        self.phones: dict[str, PairedClient] = {}
        self.revision: int = 1
        self.server_time_ms: int = 1795340084000
        self.journal_entries: list[dict[str, Any]] = []
        self._rev_event = asyncio.Event()
        self._waiters: dict[str, asyncio.Event] = {}
        self._runner: web.AppRunner | None = None
        self.host: str = "127.0.0.1"
        self.port: int = 0
        self.machine: dict[str, Any] = {
            "link": "READY",
            "linkLabel": "Base prête",
            "ready": True,
            "faultCode": "",
            "faultMessage": "",
            "hasSample": True,
            "tempC": 42,
            "targetTempC": 0,
            "hot": False,
            "weightG": 120,
            "scaleStable": True,
            "lidOpen": False,
            "bowlDetected": True,
            "bowlRemoved": False,
            "motorOn": False,
            "heaterOn": False,
            "turbo": False,
        }
        self.job: dict[str, Any] | None = None
        self.session: dict[str, Any] | None = None
        self.waiting: dict[str, Any] | None = None
        self.last_activity: dict[str, Any] | None = None
        self.can: dict[str, dict[str, Any]] = {
            "pause": {"allowed": False, "code": "nothing_running", "reason": "Aucun programme en cours"},
            "resume": {"allowed": False, "code": "not_paused", "reason": "Le programme n'est pas en pause"},
            "stop": {"allowed": False, "code": "nothing_running", "reason": "Aucun programme en cours"},
            "tare": {"allowed": True, "code": "", "reason": ""},
        }

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/api/hello", self._handle_hello)
        app.router.add_post("/api/pair", self._handle_pair)
        app.router.add_post("/api/prove", self._handle_prove)
        app.router.add_get("/api/robot", self._handle_robot)
        app.router.add_get("/api/state", self._handle_state)
        app.router.add_get("/api/journal", self._handle_journal)
        app.router.add_post("/api/machine/{action}", self._handle_machine)
        app.router.add_delete("/api/phones/me", self._handle_forget)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._wake_all()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------ helpers

    def open_pairing(self, code: str = "482913", secret: str | None = None) -> tuple[str, str]:
        self.pairing_code = code
        self.pairing_secret = secret or secrets.token_hex(16)
        self.pairing_expired = False
        self.pairing_failures = 0
        self.pairing_dead = False
        return self.pairing_code, self.pairing_secret

    def qr_text(self) -> str:
        assert self.pairing_secret is not None
        return (
            f"toque://pair?v={self.protocol}&h={self.host}&p={self.port}"
            f"&s={self.pairing_secret}&r={self.robot_id}"
        )

    def add_paired_client(self, token: str | None = None, phone_id: str | None = None) -> tuple[str, str]:
        tok = token or secrets.token_hex(32)
        pid = phone_id or secrets.token_hex(4)
        num = len(self.phones) + 1
        self.phones[pid] = PairedClient(id=pid, number=num, token_hash=sha256_hex(tok))
        return tok, pid

    def bump_revision(self, new_revision: int | None = None) -> int:
        self.revision = new_revision if new_revision is not None else self.revision + 1
        self._wake_all()
        return self.revision

    def add_journal_entry(
        self,
        *,
        kind: str,
        alert: str,
        text: str,
        detail: str = "",
        age_ms: int = 0,
        seq: int | None = None,
    ) -> dict[str, Any]:
        next_seq = seq if seq is not None else (self.journal_entries[0]["seq"] + 1 if self.journal_entries else 1)
        entry = {
            "seq": next_seq,
            "at": self.server_time_ms - age_ms,
            "kind": kind,
            "text": text,
            "alert": alert,
            "origin": {"kind": "robot", "phoneId": "", "name": "", "self": False},
            "activityId": 1,
            "stepIndex": -1,
            "elapsedMs": 0,
            "detail": detail,
        }
        self.journal_entries.insert(0, entry)
        self.bump_revision()
        return entry

    def _wake_all(self) -> None:
        self._rev_event.set()
        self._rev_event = asyncio.Event()
        for ev in list(self._waiters.values()):
            ev.set()

    def _authenticate(self, request: web.Request) -> PairedClient | None:
        auth = request.headers.get("Authorization")
        self.seen_auth_headers.append((request.method, request.path, auth))
        if not auth or not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        if len(token) != 64:
            return None
        token_hash = sha256_hex(token)
        for phone in self.phones.values():
            if hmac.compare_digest(phone.token_hash, token_hash):
                return phone
        return None

    @staticmethod
    def _err(status: int, code: str, message: str) -> web.Response:
        return web.json_response({"error": {"code": code, "message": message}}, status=status)

    def _robot_wire(self) -> dict[str, Any]:
        return {
            "id": self.robot_id,
            "name": self.robot_name,
            "appVersion": self.app_version,
            "language": "fr",
            "protocol": self.protocol,
            "model": self.model,
        }

    def _phone_wire(self, p: PairedClient) -> dict[str, Any]:
        return {
            "id": p.id,
            "number": p.number,
            "name": f"Téléphone {p.number}",
            "pairedAt": p.paired_at,
            "lastSeenAt": p.last_seen_at,
            "method": p.method,
        }

    def _state_wire(self, phone: PairedClient) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "revision": self.revision,
            "serverTime": self.server_time_ms,
            "robot": self._robot_wire(),
            "me": self._phone_wire(phone),
            "machine": dict(self.machine),
            "job": dict(self.job) if self.job is not None else None,
            "can": {k: dict(v) for k, v in self.can.items()},
            "session": dict(self.session) if self.session is not None else None,
            "waiting": dict(self.waiting) if self.waiting is not None else None,
            "last": dict(self.last_activity) if self.last_activity is not None else None,
            "journalSeq": self.journal_entries[0]["seq"] if self.journal_entries else 0,
            "limits": {"temperaturesC": [37, 60, 100, 120], "maxSpeed": 10},
        }

    # ------------------------------------------------------------------ routes

    async def _handle_hello(self, request: web.Request) -> web.Response:
        pairing_open = (
            self.pairing_code is not None
            and not self.pairing_expired
            and not self.pairing_dead
        )
        return web.json_response(
            {"service": self.service, "protocol": self.protocol, "pairing": pairing_open}
        )

    async def _handle_pair(self, request: web.Request) -> web.Response:
        body = await request.json()
        code = body.get("code")
        secret = body.get("secret")
        if bool(code) == bool(secret):
            return self._err(400, "bad_request", "Give either code or secret")
        if self.pairing_code is None:
            return self._err(410, "pairing_closed", "Aucun code d'appairage en cours")
        if self.pairing_dead:
            return self._err(410, "code_dead", "Trop d'essais")
        if self.pairing_expired:
            return self._err(410, "code_expired", "Code expiré")

        matched = (
            hmac.compare_digest(str(code), self.pairing_code)
            if code is not None
            else hmac.compare_digest(str(secret), self.pairing_secret or "")
        )
        if not matched:
            self.pairing_failures += 1
            if self.pairing_failures >= 5:
                self.pairing_dead = True
                return self._err(410, "code_dead", "Trop d'essais")
            return self._err(403, "wrong_code", "Code incorrect")

        if len(self.phones) >= self.max_phones:
            return self._err(409, "too_many_phones", "Trop de téléphones appairés")

        token = secrets.token_hex(32)
        phone_id = secrets.token_hex(4)
        num = 1
        used = {p.number for p in self.phones.values()}
        while num in used:
            num += 1
        phone = PairedClient(
            id=phone_id,
            number=num,
            token_hash=sha256_hex(token),
            method="code" if code is not None else "qr",
        )
        self.phones[phone_id] = phone
        self.pairing_code = None
        self.pairing_secret = None
        return web.json_response(
            {
                "token": token,
                "phone": self._phone_wire(phone),
                "robot": self._robot_wire(),
            }
        )

    async def _handle_prove(self, request: web.Request) -> web.Response:
        body = await request.json()
        phone_id = str(body.get("phoneId") or "")
        nonce = str(body.get("nonce") or "")
        if len(phone_id) != 8 or len(nonce) != 32:
            return self._err(400, "bad_request", "phoneId (8 hex) and nonce (32 hex) required")
        phone = self.phones.get(phone_id)
        if phone is None or self.corrupt_proof:
            key = sha256_hex("decoy-" + phone_id)
        else:
            key = phone.token_hash
        proof = compute_proof(key, nonce, self.robot_id, self.host)
        return web.json_response({"proof": proof})

    async def _handle_robot(self, request: web.Request) -> web.Response:
        phone = self._authenticate(request)
        if phone is None:
            return self._err(401, "unauthorized", "Non appairé")
        return web.json_response({"robot": self._robot_wire(), "phone": self._phone_wire(phone)})

    async def _handle_state(self, request: web.Request) -> web.Response:
        phone = self._authenticate(request)
        if phone is None:
            return self._err(401, "unauthorized", "Non appairé")

        since_raw = request.query.get("since")
        if since_raw is not None:
            since = int(since_raw)
            wait = min(120, max(0, int(request.query.get("wait", "20"))))
            replace = request.query.get("replace") == "1"
            if replace and phone.id in self._waiters:
                self._waiters[phone.id].set()

            if since == self.revision and wait > 0:
                my_ev = asyncio.Event()
                self._waiters[phone.id] = my_ev
                rev_ev = self._rev_event
                self.active_long_polls += 1
                self.max_concurrent_long_polls = max(
                    self.max_concurrent_long_polls, self.active_long_polls
                )
                try:
                    t1 = asyncio.create_task(my_ev.wait())
                    t2 = asyncio.create_task(rev_ev.wait())
                    done, pending = await asyncio.wait(
                        {t1, t2}, timeout=wait, return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in pending:
                        t.cancel()
                finally:
                    self.active_long_polls -= 1
                    if self._waiters.get(phone.id) is my_ev:
                        self._waiters.pop(phone.id, None)

        return web.json_response(self._state_wire(phone))

    async def _handle_journal(self, request: web.Request) -> web.Response:
        phone = self._authenticate(request)
        if phone is None:
            return self._err(401, "unauthorized", "Non appairé")
        after = int(request.query.get("after", "0"))
        limit = int(request.query.get("limit", "100"))
        entries = [e for e in self.journal_entries if e["seq"] > after][:limit]
        last_seq = self.journal_entries[0]["seq"] if self.journal_entries else 0
        return web.json_response({"lastSeq": last_seq, "entries": entries, "activities": []})

    async def _handle_machine(self, request: web.Request) -> web.Response:
        phone = self._authenticate(request)
        if phone is None:
            return self._err(401, "unauthorized", "Non appairé")
        action = request.match_info["action"]
        self.action_calls.append(action)

        if action in self.action_override:
            status, code, msg = self.action_override[action]
            return self._err(status, code, msg)

        perm = self.can.get(action)
        if not perm or not perm.get("allowed"):
            return self._err(
                409,
                (perm or {}).get("code", "refused"),
                (perm or {}).get("reason", "Action refusée"),
            )

        if action == "tare":
            self.machine["weightG"] = 0
        elif action == "pause" and self.job is not None:
            self.job["state"] = "PAUSED"
            self.job["counting"] = False
            self.can["pause"] = {"allowed": False, "code": "nothing_running", "reason": "Déjà en pause"}
        elif action == "stop" and self.job is not None:
            self.job["state"] = "ABORTED"
            self.job["counting"] = False
            self.can["pause"] = {"allowed": False, "code": "nothing_running", "reason": "Arrêté"}
            self.can["stop"] = {"allowed": False, "code": "nothing_running", "reason": "Arrêté"}

        rev = self.bump_revision()
        return web.json_response({"ok": True, "revision": rev})

    async def _handle_forget(self, request: web.Request) -> web.Response:
        phone = self._authenticate(request)
        if phone is None:
            return self._err(401, "unauthorized", "Non appairé")
        self.phones.pop(phone.id, None)
        rev = self.bump_revision()
        return web.json_response({"ok": True, "revision": rev})
