"""Constants for the Voltie Charger integration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "voltie_charger"
MANUFACTURER = "Voltie"
DEFAULT_MODEL = "Voltie Charger"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

API_PORT = 5059
# Per-request timeout; the coordinator retries once on failure.
REQUEST_TIMEOUT = 6
HA_START_NAME = "homeassistant"

UPDATE_RETRY_COUNT = 1
UPDATE_RETRY_BACKOFF_S = 1.0
# /config re-probe cadence (coordinator ticks) after the soft-fail latch.
CONFIG_REPROBE_EVERY = 20

ENDPOINT_STATUS = "status"
ENDPOINT_POWER = "power"
ENDPOINT_CONFIG = "config"
ENDPOINT_START = "start"
ENDPOINT_STOP = "stop"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300

CONF_SCAN_INTERVAL = "scan_interval"

DATA_STATUS = "status"
DATA_POWER = "power"
DATA_CONFIG = "config"

CURRENT_LIMIT_MIN = 6
CURRENT_LIMIT_MAX = 32
CURRENT_LIMIT_STEP = 1

# Values mirror the charger firmware's internal EVSE state enum. State 4 is
# omitted (documented as obsolete).
EVSE_STATES: dict[int, str] = {
    0: "unknown",
    1: "ev_not_connected",
    2: "ev_connected_not_charging",
    3: "ev_connected_charging",
    5: "diode_check_failed",
    6: "gfci_fault",
    7: "no_ground",
    8: "stuck_relay",
    9: "gfi_self_test_failure",
    10: "over_temperature",
    11: "over_current",
    12: "i2c_bus_error",
    13: "ev_fault",
    14: "over_humidity",
    15: "phase_misconnected",
    16: "overvoltage",
    17: "undervoltage",
}
EVSE_STATE_ERROR = "error"
