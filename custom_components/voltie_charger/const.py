"""Constants for the Voltie Charger integration."""
from __future__ import annotations

from datetime import timedelta
import re

from homeassistant.const import Platform

DOMAIN = "voltie_charger"
MANUFACTURER = "Voltie"
DEFAULT_MODEL = "Voltie Charger"

# The firmware names the charger "voltiecharger-" plus the last four characters
# of its charger ID, as both hostname and mDNS instance name (voltie-rpi
# rewriteHostName()). The group is that suffix.
MDNS_NAME_RE = re.compile(r"voltiecharger-([0-9a-f]{4})(?![0-9a-f])", re.IGNORECASE)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

API_PORT = 5059
# Per-request timeout; the coordinator retries once on failure.
REQUEST_TIMEOUT = 6
HA_START_NAME = "homeassistant"

UPDATE_RETRY_COUNT = 1
UPDATE_RETRY_BACKOFF_S = 1.0
# Soft-fail re-probe cadence (coordinator ticks) for optional endpoints.
CONFIG_REPROBE_EVERY = 20

ENDPOINT_APIVER = "apiver"
ENDPOINT_CDR = "cdr"
ENDPOINT_STATUS = "status"
ENDPOINT_POWER = "power"
ENDPOINT_CONFIG = "config"
ENDPOINT_START = "start"
ENDPOINT_STOP = "stop"
ENDPOINT_EXTRAS = "extras"
ENDPOINT_RFID = "rfid"
ENDPOINT_RFID_STATUS = "rfid/status"
ENDPOINT_RFID_EXTRAS = "rfid/extras"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300

CONF_SCAN_INTERVAL = "scan_interval"

DATA_STATUS = "status"
DATA_POWER = "power"
DATA_CONFIG = "config"
DATA_RFID_STATUS = "rfid_status"

# /status field for the charger's lifetime meter reading in kWh: the MID meter
# where one is fitted, the EVSE's lifetime counter otherwise, and -1 while
# neither has a fresh reading. Proposed in VLT-2675 (A7) and not in any
# firmware yet, so everything that reads it copes with its absence.
STATUS_METER_KWH = "meter_kwh"

# Oldest HTTP API major version with every feature this integration offers.
MIN_FULL_API_VERSION = 5

# Repair issue translation keys; issue IDs add the config entry ID.
ISSUE_OUTDATED_FIRMWARE = "outdated_firmware"
ISSUE_UNAUTHENTICATED_API = "unauthenticated_api"
# How often to look again whether the HTTP API still answers anonymously.
AUTH_RECHECK_INTERVAL = timedelta(hours=1)

# Charging-session tracking, persisted so a session that ends while Home
# Assistant is down is still reported once it is back.
SESSION_STORE_VERSION = 1
EVENT_SESSION_FINISHED = "session_finished"

CURRENT_LIMIT_MIN = 6
CURRENT_LIMIT_MAX = 32
CURRENT_LIMIT_STEP = 1

# Ranges from the v5.0 spec, appendix 5.4 (configuration parameters), except
# the building limit: the spec caps it at 32 A, but 3x40 A and 3x63 A supplies
# are common, so Voltie raised it to 200 A (VLT-2675). Firmware that still
# enforces 32 A drops a higher value, which async_set_config reports.
DLM_CURRENT_LIMIT_MIN = 6
DLM_CURRENT_LIMIT_MAX = 200
ECO_START_CURRENT_MIN = 1
ECO_START_CURRENT_MAX = 5
GRID_VOLTAGE_MIN = 200
GRID_VOLTAGE_MAX = 300
GRID_TIMEOUT_MIN = 0
GRID_TIMEOUT_MAX = 300

# /config enum keys. The option strings double as translation keys.
DLM_MODES: dict[int, str] = {
    0: "off",
    1: "dynamic",
    2: "eco",
    3: "green",
    4: "grid_control",
}

ACCESS_MODES: dict[int, str] = {
    0: "home_charger",
    1: "home_charger_rfid",
}

# conf_force_single_phase: only 0 and 1 may be written. 2 and 3 are status
# values that appear in read responses only (spec 4.7).
FORCE_SINGLE_PHASE_OFF = 0
FORCE_SINGLE_PHASE_ON = 1
FORCE_SINGLE_PHASE_NOT_SUPPORTED = 2
FORCE_SINGLE_PHASE_UNKNOWN = 3

# /extras commands (spec 4.10).
CMD_DISPLAY_SCROLL_TEXT = "display_scroll_text"
CMD_REAR_LED_SET = "rear_led_set"
CMD_CHARGER_REBOOT = "charger_reboot"

# /rfid/extras commands (spec 4.11.6).
CMD_RFID_LEARN = "rfid_learn"
CMD_RFID_LEARN_CANCEL = "rfid_learn_cancel"

# display_scroll_text parameter bounds (spec 4.10.1).
DISPLAY_MESSAGE_MIN_LEN = 1
DISPLAY_MESSAGE_MAX_LEN = 100
DISPLAY_REPEAT_MIN = 1
DISPLAY_REPEAT_MAX = 5
DISPLAY_REPEAT_DEFAULT = 1

# rear_led_set parameter bounds (spec 4.10.2).
LED_BRIGHTNESS_MIN = 0.0
LED_BRIGHTNESS_MAX = 1.0
LED_DURATION_MIN = 0
LED_DURATION_MAX = 3600
LED_DURATION_DEFAULT = 3600

# RFID tag field limits (spec 4.11.1).
RFID_ID_MIN_LEN = 8
RFID_ID_MAX_LEN = 20
RFID_NAME_MAX_LEN = 30
RFID_COMMENT_MAX_LEN = 40

# rfid_learn bounds (spec 4.11.6). The spec gives no range for timeout_sec, so
# the ceiling is only a UI guard rail; the firmware has the last word. The
# firmware defaults (30 s, unlimited) are applied by omitting the parameters.
RFID_LEARN_TIMEOUT_MIN = 1
RFID_LEARN_TIMEOUT_MAX = 3600

# /start parameter limits (spec 4.4).
START_ID_TAG_MIN_LEN = 8
START_ID_TAG_MAX_LEN = 20
START_NAME_MAX_LEN = 30

# Service names.
SERVICE_DISPLAY_TEXT = "display_text"
SERVICE_SET_REAR_LED = "set_rear_led"
SERVICE_START_CHARGING = "start_charging"
SERVICE_ADD_RFID_TAG = "add_rfid_tag"
SERVICE_MODIFY_RFID_TAG = "modify_rfid_tag"
SERVICE_DELETE_RFID_TAG = "delete_rfid_tag"
SERVICE_LIST_RFID_TAGS = "list_rfid_tags"
SERVICE_START_RFID_LEARN = "start_rfid_learn"

# Service call attributes.
ATTR_DEVICE_ID = "device_id"
ATTR_MESSAGE = "message"
ATTR_REPEAT_COUNT = "repeat_count"
ATTR_CLEAR_FIRST = "clear_first"
ATTR_BRIGHTNESS = "brightness"
ATTR_COLOR_RGB = "color_rgb"
ATTR_DURATION_SEC = "duration_sec"
ATTR_ID_TAG = "id_tag"
ATTR_NAME = "name"
ATTR_RFID_ID = "id"
ATTR_ENABLED = "enabled"
ATTR_COMMENT = "comment"
ATTR_FIRST_ITEM = "first_item"
ATTR_MAX_COUNT = "max_count"
ATTR_TIMEOUT_SEC = "timeout_sec"
ATTR_COUNT_MAX = "count_max"

# Values mirror the charger firmware's internal EVSE state enum (voltie-rpi
# evse_state.h), which is more detailed than the documented set in spec
# appendix 5.1. State 4 (charging with ventilation) is obsolete but still
# documented as a valid charging state, so it is mapped rather than left to
# fall through to "error".
EVSE_STATES: dict[int, str] = {
    0: "unknown",
    1: "ev_not_connected",
    2: "ev_connected_not_charging",
    3: "ev_connected_charging",
    4: "ev_connected_charging_ventilation",
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
    # conf_out_of_service puts the EVSE here.
    18: "disabled",
    19: "booting",
    20: "mid_meter_missing",
    21: "power_board_unknown",
    22: "waiting_for_timer",
    23: "shutdown",
    24: "undetermined",
    25: "firmware_update",
    26: "pe_n_fault",
}
EVSE_STATE_ERROR = "error"

# States that are not a problem. Everything else, including codes newer
# firmware may add, is. Unlike the firmware, which only counts faults of the
# charger itself, a vehicle fault (13) counts too: charging is stuck either
# way. 0 is what the charger reports before its first valid EVSE read, so
# counting it would raise a false alarm on every start.
EVSE_NON_PROBLEM_STATES = frozenset({0, 1, 2, 3, 4, 18, 19, 22, 24, 25})
