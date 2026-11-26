"""Constants for the Toque Companion integration."""

from __future__ import annotations

DOMAIN = "toque_companion"

CONF_TOKEN = "token"
CONF_PHONE_ID = "phone_id"
CONF_ROBOT_ID = "robot_id"
CONF_PAIRING_CODE = "pairing_code"
CONF_QR_TEXT = "qr_text"
CONF_SENSOR_ONLY = "sensor_only"

DEFAULT_PORT = 8088
SUPPORTED_PROTOCOL = 1
SERVICE_NAME = "toque-companion"

# Long-poll and reconnection timings (aligned with StateFollower.kt)
LONG_POLL_WAIT_S = 20
HTTP_CONNECT_TIMEOUT_S = 5.0
HTTP_READ_TIMEOUT_S = 10.0
COMMAND_TIMEOUT_S = 12.0  # Robot host call timeout is 5 s; allow margin without retrying
BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 30.0

# Journal alert freshness (COMPANION.md section 5: ignore alerts older than 2 min)
MAX_ALERT_AGE_MS = 120_000

# Event types emitted by the cooking EventEntity (matching Companion journal `alert` values)
EVENT_TYPES: list[str] = [
    "waiting",
    "step_end",
    "job_end",
    "pause",
    "fault",
    "temp_reached",
]

# Allowed machine control actions (strictly scoped to safe monitoring + pause/stop/tare)
ALLOWED_ACTIONS: frozenset[str] = frozenset({"pause", "stop", "tare"})

# Derived robot status enum values
ROBOT_STATUSES: list[str] = [
    "idle",
    "starting",
    "running",
    "paused",
    "stopping",
    "finished",
    "aborted",
    "fault",
]

LINK_STATES: list[str] = [
    "offline",
    "arming",
    "ready",
    "lost",
]
