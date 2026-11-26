"""Coordinator managing a single Companion long-poll loop and journal alerts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import (
    CompanionApiError,
    CompanionAuthError,
    CompanionError,
    CompanionProofError,
    ToqueCompanionClient,
)
from .const import (
    ALLOWED_ACTIONS,
    BACKOFF_MAX_S,
    BACKOFF_MIN_S,
    DOMAIN,
    EVENT_TYPES,
    LONG_POLL_WAIT_S,
    MAX_ALERT_AGE_MS,
)

_LOGGER = logging.getLogger(__name__)

type ToqueCompanionConfigEntry = ConfigEntry[ToqueCompanionCoordinator]


class ToqueCompanionCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Receives live state via a single long-poll loop and dispatches safe commands."""

    config_entry: ToqueCompanionConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ToqueCompanionConfigEntry,
        client: ToqueCompanionClient,
        initial_state: dict[str, Any],
        *,
        sensor_only: bool = False,
        wait_seconds: int = LONG_POLL_WAIT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
        )
        self.client = client
        self.sensor_only = sensor_only
        self._wait_seconds = wait_seconds
        self._sleep = sleep
        self._clock = clock
        self._utc_now = utc_now

        self.state: dict[str, Any] = initial_state
        self.data = initial_state
        self.robot_available: bool = True
        self.last_error: str | None = None
        self.state_received_monotonic: float = self._clock()
        self.estimated_end_utc: datetime | None = None

        self._follow_task: asyncio.Task[None] | None = None
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []

        # Journal alert tracking (no historical replay on startup)
        self._last_journal_seq: int = self._extract_journal_seq(initial_state)
        self._last_alert_wall_ms: int = int(initial_state.get("serverTime") or 0)

        self._update_estimated_end(initial_state)

    # ------------------------------------------------------------------ lifecycle

    def async_start(self) -> None:
        """Start the single long-poll background task (idempotent)."""
        if self._follow_task is not None and not self._follow_task.done():
            return
        self._follow_task = self.hass.async_create_background_task(
            self._follow_loop(),
            name=f"{DOMAIN}_{self.config_entry.entry_id}_follow",
        )

    async def async_stop(self) -> None:
        """Cancel and await the long-poll background task."""
        task = self._follow_task
        self._follow_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------ event bus

    def async_add_event_listener(
        self, listener: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a listener for journal alert events."""
        self._event_listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._event_listeners:
                self._event_listeners.remove(listener)

        return _remove

    def _emit_alert(self, alert_type: str, data: dict[str, Any]) -> None:
        for listener in list(self._event_listeners):
            listener(alert_type, data)

    # ------------------------------------------------------------------ long-poll loop

    async def _follow_loop(self) -> None:
        """Follow state changes via GET /api/state?since=<rev>&wait=<S>&replace=1."""
        since: int | None = self._extract_revision(self.state)
        delay = BACKOFF_MIN_S

        while True:
            try:
                state = await self.client.get_state(
                    since=since,
                    wait=self._wait_seconds,
                    replace=True,
                )
            except asyncio.CancelledError:
                return
            except CompanionAuthError:
                _LOGGER.warning(
                    "Toque Companion rejected the bearer token for %s:%s; starting reauthentication",
                    self.client.host,
                    self.client.port,
                )
                self._mark_unavailable("unauthorized")
                self.config_entry.async_start_reauth(self.hass)
                return
            except CompanionProofError as err:
                since = None
                self.client.invalidate_proof()
                if self.robot_available or self.last_error != "proof_failed":
                    _LOGGER.warning(
                        "Toque Companion proof failed at %s:%s (%s). "
                        "Bearer token was NOT sent. Either the robot IP changed or this "
                        "client was removed on the robot.",
                        self.client.host,
                        self.client.port,
                        err,
                    )
                self._mark_unavailable("proof_failed")
                await self._sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_S)
                continue
            except CompanionError as err:
                since = None
                self.client.invalidate_proof()
                if self.robot_available:
                    _LOGGER.debug(
                        "Toque Companion unreachable at %s:%s: %s",
                        self.client.host,
                        self.client.port,
                        err,
                    )
                self._mark_unavailable(type(err).__name__)
                await self._sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_S)
                continue
            except Exception as err:  # noqa: BLE001 - guard background loop
                since = None
                self.client.invalidate_proof()
                _LOGGER.exception("Unexpected error in Toque Companion follow loop: %s", err)
                self._mark_unavailable(type(err).__name__)
                await self._sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_S)
                continue

            delay = BACKOFF_MIN_S
            was_unavailable = not self.robot_available
            new_rev = self._extract_revision(state)
            changed = was_unavailable or since is None or new_rev != since
            since = new_rev

            self._apply_state(state)
            if changed:
                self.async_set_updated_data(state)

            await self._sync_journal(state)

    def _apply_state(self, state: dict[str, Any]) -> None:
        self.state = state
        self.robot_available = True
        self.last_error = None
        self.state_received_monotonic = self._clock()
        self._update_estimated_end(state)

    def _mark_unavailable(self, reason: str) -> None:
        changed = self.robot_available or self.last_error != reason
        self.robot_available = False
        self.last_error = reason
        self.estimated_end_utc = None
        if changed:
            self.async_update_listeners()

    def _update_estimated_end(self, state: dict[str, Any]) -> None:
        """Compute stable estimated end timestamp while job.counting is True."""
        job = state.get("job")
        if not isinstance(job, dict) or not job.get("counting"):
            self.estimated_end_utc = None
            return
        remaining_ms = job.get("remainingMs")
        if not isinstance(remaining_ms, (int, float)) or remaining_ms <= 0:
            self.estimated_end_utc = None
            return
        candidate = (self._utc_now() + timedelta(milliseconds=int(remaining_ms))).replace(
            microsecond=0
        )
        # Avoid recorder jitter when temperature ticks arrive during normal countdown
        if (
            self.estimated_end_utc is None
            or abs((candidate - self.estimated_end_utc).total_seconds()) >= 2.0
        ):
            self.estimated_end_utc = candidate

    async def _sync_journal(self, state: dict[str, Any]) -> None:
        """Fetch new journal entries when journalSeq advances or resets."""
        seq = self._extract_journal_seq(state)
        if seq == self._last_journal_seq:
            return

        server_time = int(state.get("serverTime") or 0)
        restarted = seq < self._last_journal_seq
        after = 0 if restarted else self._last_journal_seq

        if seq == 0:
            self._last_journal_seq = 0
            return

        try:
            page = await self.client.get_journal(after=after, limit=100)
        except CompanionError as err:
            _LOGGER.debug("Failed to fetch Companion journal: %s", err)
            return

        entries = page.get("entries")
        if not isinstance(entries, list):
            self._last_journal_seq = seq
            return

        highest_seq = 0 if restarted else self._last_journal_seq
        # Entries arrive newest-first; emit in chronological order
        for entry in reversed(entries):
            if not isinstance(entry, dict):
                continue
            entry_seq = int(entry.get("seq") or 0)
            if entry_seq > highest_seq:
                highest_seq = entry_seq

            alert = entry.get("alert")
            if not isinstance(alert, str) or alert not in EVENT_TYPES:
                continue

            entry_at = int(entry.get("at") or 0)
            # Skip stale alerts (> 2 minutes old) or pre-restart alerts
            if server_time > 0 and entry_at > 0 and (server_time - entry_at) > MAX_ALERT_AGE_MS:
                continue
            if restarted and entry_at > 0 and entry_at <= self._last_alert_wall_ms:
                continue

            if entry_at > self._last_alert_wall_ms:
                self._last_alert_wall_ms = entry_at

            origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
            self._emit_alert(
                alert,
                {
                    "seq": entry_seq,
                    "kind": str(entry.get("kind") or ""),
                    "text": str(entry.get("text") or ""),
                    "detail": str(entry.get("detail") or ""),
                    "step_index": entry.get("stepIndex", -1),
                    "origin_kind": str(origin.get("kind") or ""),
                    "origin_name": str(origin.get("name") or ""),
                },
            )

        self._last_journal_seq = max(highest_seq, seq)

    # ------------------------------------------------------------------ safe actions

    async def async_machine_action(self, action: str) -> None:
        """Send a strictly allowed machine command (pause, stop, or tare).

        Never retries automatically: a 504 timeout/no_answer may mean the
        command was already applied by the robot.
        """
        if self.sensor_only:
            raise HomeAssistantError(
                "Integration is configured in sensor-only mode; machine commands are disabled"
            )
        if action not in ALLOWED_ACTIONS:
            raise HomeAssistantError(f"Action not permitted: {action}")
        if not self.robot_available:
            raise HomeAssistantError("Toque robot is unavailable")

        try:
            await self.client.machine_action(action)
        except CompanionAuthError as err:
            self._mark_unavailable("unauthorized")
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError("Robot rejected pairing token") from err
        except CompanionProofError as err:
            self._mark_unavailable("proof_failed")
            raise HomeAssistantError(
                "Robot identity proof failed; command was not sent"
            ) from err
        except CompanionApiError as err:
            if err.is_timeout_or_no_answer:
                raise HomeAssistantError(
                    f"Robot did not confirm '{action}' ({err.code}); not retrying automatically"
                ) from err
            detail = err.message or err.code
            raise HomeAssistantError(f"Robot refused '{action}': {detail}") from err
        except CompanionError as err:
            raise HomeAssistantError(
                f"Failed to send '{action}' to robot: {err}"
            ) from err

    # ------------------------------------------------------------------ helpers

    @property
    def base_data_valid(self) -> bool:
        """True when robot is reachable and base has a valid sample."""
        if not self.robot_available:
            return False
        machine = self.state.get("machine")
        if not isinstance(machine, dict):
            return False
        if machine.get("link") in ("OFFLINE", "LOST"):
            return False
        return bool(machine.get("hasSample"))

    @staticmethod
    def _extract_revision(state: dict[str, Any]) -> int | None:
        rev = state.get("revision")
        return int(rev) if isinstance(rev, int) else None

    @staticmethod
    def _extract_journal_seq(state: dict[str, Any]) -> int:
        seq = state.get("journalSeq")
        return int(seq) if isinstance(seq, int) else 0
