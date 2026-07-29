"""Device-targeted services for Voltie Charger."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
import re
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .client import (
    VoltieChargerAuthError,
    VoltieChargerConnectionError,
    VoltieChargerRejectedError,
    VoltieChargerUnsupportedError,
)
from .const import (
    ATTR_BRIGHTNESS,
    ATTR_CLEAR_FIRST,
    ATTR_COLOR_RGB,
    ATTR_COMMENT,
    ATTR_COUNT_MAX,
    ATTR_DEVICE_ID,
    ATTR_DURATION_SEC,
    ATTR_ENABLED,
    ATTR_FIRST_ITEM,
    ATTR_ID_TAG,
    ATTR_MAX_COUNT,
    ATTR_MESSAGE,
    ATTR_NAME,
    ATTR_REPEAT_COUNT,
    ATTR_RFID_ID,
    ATTR_TIMEOUT_SEC,
    DISPLAY_MESSAGE_MAX_LEN,
    DISPLAY_MESSAGE_MIN_LEN,
    DISPLAY_REPEAT_MAX,
    DISPLAY_REPEAT_MIN,
    DOMAIN,
    HA_START_NAME,
    LED_BRIGHTNESS_MAX,
    LED_BRIGHTNESS_MIN,
    LED_DURATION_MAX,
    LED_DURATION_MIN,
    RFID_COMMENT_MAX_LEN,
    RFID_ID_MAX_LEN,
    RFID_ID_MIN_LEN,
    RFID_LEARN_TIMEOUT_MAX,
    RFID_LEARN_TIMEOUT_MIN,
    RFID_NAME_MAX_LEN,
    SERVICE_ADD_RFID_TAG,
    SERVICE_DELETE_RFID_TAG,
    SERVICE_DISPLAY_TEXT,
    SERVICE_LIST_RFID_TAGS,
    SERVICE_MODIFY_RFID_TAG,
    SERVICE_SET_REAR_LED,
    SERVICE_START_CHARGING,
    SERVICE_START_RFID_LEARN,
    START_ID_TAG_MAX_LEN,
    START_ID_TAG_MIN_LEN,
    START_NAME_MAX_LEN,
)

if TYPE_CHECKING:
    # Importing the coordinator at runtime would be circular: __init__ imports
    # this module before the coordinator class exists.
    from . import VoltieChargerCoordinator

# Patterns are used with re.match, so they are end-anchored with \Z.
#
# Stored RFID tags (/rfid): spec 4.11.1 documents the charset as 0-9 A-Z a-z _ -,
# but the firmware rejects anything non-hexadecimal — verified against sw 9.3.29
# and 1.3.40, where "DEADBEEF01" is accepted and "CLAUDETEST01" returns
# error_code 5. Validating here turns a baffling "charger rejected the tag" into
# a usable message. Loosen it if the firmware ever accepts the documented set.
_STORED_TAG_ID_RE = re.compile(r"[0-9A-Fa-f]+\Z")
# /start's id_tag is a different field: it is only recorded into the CDR rather
# than matched against the stored list, so it keeps the documented charset
# (spec 4.4), which permits hyphens since API 4.3.
_START_ID_TAG_RE = re.compile(r"[0-9A-Za-z_-]+\Z")
_TAG_NAME_RE = re.compile(r"[0-9A-Za-z_ -]+\Z")
# The API wants "#RRGGBB" (spec 4.10.2); a bare "RRGGBB" is accepted and
# normalised so hand-typed values in automations keep working.
_COLOR_RGB_RE = re.compile(r"#?(?P<hex>[0-9A-Fa-f]{6})\Z")

_CLIENT_ERRORS = (
    VoltieChargerAuthError,
    VoltieChargerConnectionError,
    VoltieChargerRejectedError,
)

_TARGET_DEVICE_MSG = "select the Voltie charger device this action targets"


def _unsupported_target(value: Any) -> Any:
    raise vol.Invalid(
        "target a specific Voltie charger device; areas, floors, labels and "
        "entities are not supported by this action"
    )


# HA merges the service target into call.data, so the picked device arrives as
# data[device_id] — a list from the UI, a bare string from hand-written YAML.
_DEVICE_TARGET = {
    vol.Required(ATTR_DEVICE_ID, msg=_TARGET_DEVICE_MSG): vol.All(
        cv.ensure_list, [cv.string], vol.Length(min=1)
    ),
    # Area, floor, label and entity targets are rejected rather than dropped:
    # silently ignoring them would run the command on only some of the chargers
    # the user selected, with nothing to say the rest were skipped.
    **{
        vol.Optional(key): _unsupported_target
        for key in (ATTR_AREA_ID, ATTR_ENTITY_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID)
    },
}

_TAG_ID = vol.All(
    cv.string,
    vol.Length(min=RFID_ID_MIN_LEN, max=RFID_ID_MAX_LEN),
    vol.Match(
        _STORED_TAG_ID_RE,
        msg="an RFID tag ID must be hexadecimal (0-9, A-F)",
    ),
)

_RFID_TAG_FIELDS = {
    vol.Optional(ATTR_NAME): vol.All(cv.string, vol.Length(max=RFID_NAME_MAX_LEN)),
    vol.Optional(ATTR_ENABLED): cv.boolean,
    vol.Optional(ATTR_COMMENT): vol.All(
        cv.string, vol.Length(max=RFID_COMMENT_MAX_LEN)
    ),
}

DISPLAY_TEXT_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required(ATTR_MESSAGE): vol.All(
            cv.string,
            vol.Length(min=DISPLAY_MESSAGE_MIN_LEN, max=DISPLAY_MESSAGE_MAX_LEN),
        ),
        vol.Optional(ATTR_REPEAT_COUNT): vol.All(
            vol.Coerce(int), vol.Range(min=DISPLAY_REPEAT_MIN, max=DISPLAY_REPEAT_MAX)
        ),
        vol.Optional(ATTR_CLEAR_FIRST): cv.boolean,
    }
)

SET_REAR_LED_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required(ATTR_BRIGHTNESS): vol.All(
            vol.Coerce(float),
            vol.Range(min=LED_BRIGHTNESS_MIN, max=LED_BRIGHTNESS_MAX),
        ),
        # Shape is checked in the handler so a bad colour produces a readable
        # ServiceValidationError instead of a voluptuous dump.
        vol.Required(ATTR_COLOR_RGB): cv.string,
        vol.Optional(ATTR_DURATION_SEC): vol.All(
            vol.Coerce(int), vol.Range(min=LED_DURATION_MIN, max=LED_DURATION_MAX)
        ),
    }
)

START_CHARGING_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Optional(ATTR_ID_TAG): vol.All(
            cv.string,
            vol.Length(min=START_ID_TAG_MIN_LEN, max=START_ID_TAG_MAX_LEN),
            vol.Match(
                _START_ID_TAG_RE,
                msg="only letters, digits, '_' and '-' are allowed",
            ),
        ),
        vol.Optional(ATTR_NAME): vol.All(
            cv.string,
            vol.Length(max=START_NAME_MAX_LEN),
            vol.Match(
                _TAG_NAME_RE,
                msg="only letters, digits, spaces, '_' and '-' are allowed",
            ),
        ),
    }
)

ADD_RFID_TAG_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required(ATTR_RFID_ID): _TAG_ID,
        **_RFID_TAG_FIELDS,
    }
)

# Identical wire fields to add; the "at least one field to change" rule cannot
# be expressed in voluptuous and is enforced in the handler.
MODIFY_RFID_TAG_SCHEMA = ADD_RFID_TAG_SCHEMA

DELETE_RFID_TAG_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required(ATTR_RFID_ID): _TAG_ID,
    }
)

START_RFID_LEARN_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Optional(ATTR_TIMEOUT_SEC): vol.All(
            vol.Coerce(int),
            vol.Range(min=RFID_LEARN_TIMEOUT_MIN, max=RFID_LEARN_TIMEOUT_MAX),
        ),
        vol.Optional(ATTR_COUNT_MAX): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)

LIST_RFID_TAGS_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Optional(ATTR_FIRST_ITEM): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_MAX_COUNT): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)


def _to_ha_error(exc: Exception) -> HomeAssistantError:
    if isinstance(exc, VoltieChargerAuthError):
        return HomeAssistantError(f"Authentication failed: {exc}")
    # Checked before the rejected error it subclasses.
    if isinstance(exc, VoltieChargerUnsupportedError):
        return HomeAssistantError(
            f"This charger's firmware does not support that command ({exc}). "
            "Update the charger firmware, or check that its hardware has the "
            "feature."
        )
    if isinstance(exc, VoltieChargerRejectedError):
        return HomeAssistantError(f"Charger rejected the request: {exc}")
    if isinstance(exc, VoltieChargerConnectionError):
        return HomeAssistantError(f"Cannot reach charger: {exc}")
    return HomeAssistantError(str(exc))


async def _guard(coro: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
    """Await a client call, translating charger failures for the UI."""
    try:
        return await coro
    except _CLIENT_ERRORS as exc:
        raise _to_ha_error(exc) from exc


def _resolve_coordinator(call: ServiceCall) -> VoltieChargerCoordinator:
    """Resolve the targeted device to its loaded coordinator."""
    device_ids: list[str] = call.data[ATTR_DEVICE_ID]
    # One device per call: list_rfid_tags returns a single response and the rest
    # report per-charger failures, neither of which fans out meaningfully.
    if len(device_ids) != 1:
        raise ServiceValidationError(
            "Target exactly one Voltie charger; call the service once per "
            "charger instead."
        )
    device_id = device_ids[0]

    device = dr.async_get(call.hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            f"No device with ID {device_id} exists; pick the charger again."
        )

    for entry_id in device.config_entries:
        entry = call.hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            break
    else:
        raise ServiceValidationError(
            f"{device.name_by_user or device.name or device_id} is not a "
            "Voltie charger."
        )

    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            f"The Voltie charger {device.name_by_user or device.name} is not "
            f"set up (state: {entry.state.value}); check that it is reachable, "
            "then reload the integration."
        )
    return entry.runtime_data


def _require_rfid(coordinator: VoltieChargerCoordinator) -> None:
    """Fail fast instead of letting the request 404 on old firmware."""
    if not coordinator.rfid_supported:
        raise ServiceValidationError(
            "This charger does not expose the RFID tag API; it requires API v5 "
            "firmware."
        )


def _normalise_color(value: str) -> str:
    match = _COLOR_RGB_RE.match(value.strip())
    if match is None:
        raise ServiceValidationError(
            f"'{value}' is not a hex RGB colour; use a value like #FF8800."
        )
    return f"#{match.group('hex').upper()}"


async def _async_display_text(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call)
    await _guard(
        coordinator.client.async_display_scroll_text(
            call.data[ATTR_MESSAGE],
            repeat_count=call.data.get(ATTR_REPEAT_COUNT),
            clear_first=call.data.get(ATTR_CLEAR_FIRST),
        )
    )


async def _async_set_rear_led(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call)
    await _guard(
        coordinator.client.async_set_rear_led(
            brightness=call.data[ATTR_BRIGHTNESS],
            color_rgb=_normalise_color(call.data[ATTR_COLOR_RGB]),
            duration_sec=call.data.get(ATTR_DURATION_SEC),
        )
    )


async def _async_start_charging(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call)
    await _guard(
        coordinator.client.async_start(
            id_tag=call.data.get(ATTR_ID_TAG),
            # Same identifier the charging switch sends, so sessions started
            # either way look the same in the charger's records.
            name=call.data.get(ATTR_NAME, HA_START_NAME),
        )
    )
    await coordinator.async_request_refresh()


async def _async_add_rfid_tag(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call)
    _require_rfid(coordinator)
    try:
        await coordinator.client.async_add_rfid_tag(
            call.data[ATTR_RFID_ID],
            name=call.data.get(ATTR_NAME),
            enabled=call.data.get(ATTR_ENABLED),
            comment=call.data.get(ATTR_COMMENT),
        )
    except VoltieChargerUnsupportedError as exc:
        # Matched before the rejected error it subclasses, so "your firmware
        # cannot do this" is never reported as a duplicate tag.
        raise _to_ha_error(exc) from exc
    except VoltieChargerRejectedError as exc:
        # The schema already enforced length and the hex charset, so the generic
        # "incorrect parameter" the charger returns here is almost always a
        # duplicate (spec 4.11.3 uses error_code 5 for both).
        raise HomeAssistantError(
            f"Charger rejected the tag: {exc}. A tag with ID "
            f"{call.data[ATTR_RFID_ID]} is probably already stored."
        ) from exc
    except _CLIENT_ERRORS as exc:
        raise _to_ha_error(exc) from exc
    # list_count and list_hash come from /rfid/status, so without this the
    # sensors would report the pre-change list until the next scheduled poll.
    await coordinator.async_request_refresh()


async def _async_modify_rfid_tag(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call)
    _require_rfid(coordinator)

    name = call.data.get(ATTR_NAME)
    enabled = call.data.get(ATTR_ENABLED)
    comment = call.data.get(ATTR_COMMENT)
    # An id-only PUT would change nothing (spec 4.11.4 treats absent fields as
    # "leave unchanged"), so it is a user error rather than a charger error.
    if name is None and enabled is None and comment is None:
        raise ServiceValidationError(
            "Provide at least one of name, enabled or comment to change."
        )

    await _guard(
        coordinator.client.async_modify_rfid_tag(
            call.data[ATTR_RFID_ID],
            name=name,
            enabled=enabled,
            comment=comment,
        )
    )
    await coordinator.async_request_refresh()


async def _async_delete_rfid_tag(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call)
    _require_rfid(coordinator)
    await _guard(coordinator.client.async_delete_rfid_tag(call.data[ATTR_RFID_ID]))
    await coordinator.async_request_refresh()


async def _async_start_rfid_learn(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call)
    _require_rfid(coordinator)
    await _guard(
        coordinator.client.async_rfid_learn(
            timeout_sec=call.data.get(ATTR_TIMEOUT_SEC),
            count_max=call.data.get(ATTR_COUNT_MAX),
        )
    )
    # learn_in_progress / learn_to_sec are only visible via /rfid/status.
    await coordinator.async_request_refresh()


async def _async_list_rfid_tags(call: ServiceCall) -> ServiceResponse:
    coordinator = _resolve_coordinator(call)
    _require_rfid(coordinator)
    payload = await _guard(
        coordinator.client.async_get_rfid_tags(
            first_item=call.data.get(ATTR_FIRST_ITEM),
            max_count=call.data.get(ATTR_MAX_COUNT),
        )
    )

    raw_tags = payload.get("rfid_list")
    usable = isinstance(raw_tags, list)
    tags = [t for t in raw_tags if isinstance(t, dict)] if usable else []
    count = payload.get("rfid_count")
    # Only trust the charger's own count when its list was usable, so the
    # response can never claim more tags than it actually carries.
    reported = (
        count
        if usable and isinstance(count, int) and not isinstance(count, bool)
        else len(tags)
    )
    # Deliberately a service response rather than entity attributes: the list
    # holds up to 200 tags, which the recorder would store on every state write.
    return {
        "tags": tags,
        "count": reported,
        "list_hash": str(payload.get("list_hash") or ""),
    }


_SERVICES: tuple[
    tuple[
        str,
        Callable[[ServiceCall], Coroutine[Any, Any, ServiceResponse | None]],
        vol.Schema,
        SupportsResponse,
    ],
    ...,
] = (
    (
        SERVICE_DISPLAY_TEXT,
        _async_display_text,
        DISPLAY_TEXT_SCHEMA,
        SupportsResponse.NONE,
    ),
    (
        SERVICE_SET_REAR_LED,
        _async_set_rear_led,
        SET_REAR_LED_SCHEMA,
        SupportsResponse.NONE,
    ),
    (
        SERVICE_START_CHARGING,
        _async_start_charging,
        START_CHARGING_SCHEMA,
        SupportsResponse.NONE,
    ),
    (
        SERVICE_ADD_RFID_TAG,
        _async_add_rfid_tag,
        ADD_RFID_TAG_SCHEMA,
        SupportsResponse.NONE,
    ),
    (
        SERVICE_MODIFY_RFID_TAG,
        _async_modify_rfid_tag,
        MODIFY_RFID_TAG_SCHEMA,
        SupportsResponse.NONE,
    ),
    (
        SERVICE_DELETE_RFID_TAG,
        _async_delete_rfid_tag,
        DELETE_RFID_TAG_SCHEMA,
        SupportsResponse.NONE,
    ),
    (
        SERVICE_START_RFID_LEARN,
        _async_start_rfid_learn,
        START_RFID_LEARN_SCHEMA,
        SupportsResponse.NONE,
    ),
    (
        SERVICE_LIST_RFID_TAGS,
        _async_list_rfid_tags,
        LIST_RFID_TAGS_SCHEMA,
        SupportsResponse.ONLY,
    ),
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the device-targeted services.

    Called from async_setup, so registration survives config entry reloads and
    must tolerate being called again.
    """
    for name, handler, schema, supports_response in _SERVICES:
        if hass.services.has_service(DOMAIN, name):
            continue
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=supports_response,
        )
