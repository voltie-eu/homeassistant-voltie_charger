"""Entity behaviour tests, including the API v5 additions."""
from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.voltie_charger.const import DOMAIN

from .conftest import (
    charger_device,
    BASE,
    CHARGER_ID,
    ack,
    cdr_payload,
    config_payload,
    legacy_config_payload,
    rfid_status_payload,
    setup_integration,
    status_payload,
)

# The entity_id prefix HA derives from the device name "Voltie Charger 4335".
PREFIX = "voltie_charger_4335"


def _eid(domain: str, key: str) -> str:
    return f"{domain}.{PREFIX}_{key}"


async def test_new_status_sensors(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """phases_used and current_hw_limit are exposed (ticket section 1)."""
    mock_charger(status=status_payload(phases_used=3, current_hw_limit=32))
    await setup_integration(hass, config_entry)

    assert hass.states.get(_eid("sensor", "active_phases")).state == "3"
    assert hass.states.get(_eid("sensor", "hardware_current_limit")).state == "32"
    # "phases" still means the wiring, and stays an enum.
    assert hass.states.get(_eid("sensor", "phases_wired")).state == "3"


async def test_phases_used_zero_when_idle(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """0 is a real value, not 'unknown'; an enum sensor would have logged.

    Named "Active phases" rather than "Phases in use": on an upgraded install the
    pre-existing `phases` sensor already owns the `..._phases_in_use` entity_id,
    so reusing that name produced two entities whose ids differed only by an area
    prefix.
    """
    mock_charger(status=status_payload(phases_used=0))
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("sensor", "active_phases")).state == "0"


@pytest.mark.parametrize("apiver", [5, None])
async def test_api_version_is_in_diagnostics(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, apiver
) -> None:
    """Formerly a sensor; a 404 on /apiver must not break setup."""
    from custom_components.voltie_charger.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    mock_charger(apiver=apiver, rfid_supported=apiver is not None)
    await setup_integration(hass, config_entry)
    assert config_entry.state.name == "LOADED"
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["coordinator"]["api_version"] == apiver


async def test_debug_sensors_are_gone(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    entity_registry_enabled_by_default: None,
) -> None:
    """The built-in integration keeps these values in diagnostics only."""
    mock_charger()
    await setup_integration(hass, config_entry)
    keys = {
        e.unique_id.removeprefix(f"{CHARGER_ID}_")
        for e in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    }
    assert keys.isdisjoint({"api_version", "rfid_list_hash", "rfid_list_format_ver"})


async def test_evse_state_4_is_not_an_error(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """State 4 is obsolete but documented as a charging state (spec 5.1)."""
    mock_charger(status=status_payload(evse_state=4))
    await setup_integration(hass, config_entry)
    state = hass.states.get(_eid("sensor", "evse_state"))
    assert state.state == "ev_connected_charging_ventilation"


@pytest.mark.parametrize(
    "raw",
    [
        # Before the first valid EVSE reading.
        0,
        # A code newer firmware adds; the problem sensor still flags it.
        99,
        "3",
        None,
    ],
)
async def test_evse_state_without_an_option_is_unknown(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, raw
) -> None:
    """As in the built-in integration: no "unknown" or "error" option."""
    status = status_payload(evse_state=raw)
    if raw is None:
        status.pop("evse_state")
    mock_charger(status=status)
    await setup_integration(hass, config_entry)
    state = hass.states.get(_eid("sensor", "evse_state"))
    assert state.state == STATE_UNKNOWN
    assert "unknown" not in state.attributes["options"]
    assert "error" not in state.attributes["options"]


async def test_out_of_service_is_not_an_error(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """conf_out_of_service puts the EVSE in state 18, which read as "error"."""
    mock_charger(status=status_payload(evse_state=18))
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("sensor", "evse_state")).state == "disabled"
    assert hass.states.get(_eid("binary_sensor", "problem")).state == STATE_OFF


# ---- problem binary sensor (VLT-2891) ----


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        # Before the first valid EVSE read: no false alarm at startup.
        (0, STATE_OFF),
        (1, STATE_OFF),
        (3, STATE_OFF),
        (6, STATE_ON),
        (7, STATE_ON),
        # The vehicle's fault rather than the charger's, but charging is stuck.
        (13, STATE_ON),
        # Out of service, booting, a scheduled wait, a firmware update.
        (18, STATE_OFF),
        (19, STATE_OFF),
        (22, STATE_OFF),
        (24, STATE_OFF),
        (25, STATE_OFF),
        (20, STATE_ON),
        (26, STATE_ON),
        # A code newer firmware adds.
        (99, STATE_ON),
    ],
)
async def test_problem_sensor(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    code: int,
    expected: str,
) -> None:
    mock_charger(status=status_payload(evse_state=code))
    await setup_integration(hass, config_entry)
    state = hass.states.get(_eid("binary_sensor", "problem"))
    assert state.state == expected
    assert state.attributes["device_class"] == "problem"
    # The fault itself is the EVSE state sensor's; the attributes are gone.
    assert "error" not in state.attributes
    assert "raw_code" not in state.attributes


@pytest.mark.parametrize("raw", [None, "6", True])
async def test_problem_sensor_unknown_without_a_state(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, raw
) -> None:
    status = status_payload(evse_state=raw)
    if raw is None:
        status.pop("evse_state")
    mock_charger(status=status)
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("binary_sensor", "problem")).state == "unknown"


# ---- total energy (VLT-2891) ----


async def test_total_energy_needs_firmware_support(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """No firmware reports meter_kwh yet; a permanently unknown entity helps no one."""
    mock_charger()
    await setup_integration(hass, config_entry)
    assert entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{CHARGER_ID}_total_energy"
    ) is None


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        (1523.4, "1523.4"),
        # A real zero, a brand-new charger.
        (0, "0"),
        # The firmware's "no fresh reading"; a 0 would register as a meter reset.
        (-1, "unknown"),
        (None, "unknown"),
        ("1523.4", "unknown"),
        (True, "unknown"),
    ],
)
async def test_total_energy_reading(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    reading,
    expected: str,
) -> None:
    mock_charger(status=status_payload(meter_kwh=reading))
    await setup_integration(hass, config_entry)
    state = hass.states.get(_eid("sensor", "total_energy"))
    assert state.state == expected
    assert state.attributes["state_class"] == "total_increasing"
    assert state.attributes["device_class"] == "energy"
    assert state.attributes["unit_of_measurement"] == "kWh"


async def test_hungarian_translation_is_loaded(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """translations/hu.json names the entities on a Hungarian system (VLT-2890).

    Hungarian is one of the languages HA also derives new entity IDs from, so a
    fresh install there gets Hungarian object IDs rather than the English ones.
    """
    hass.config.language = "hu"
    mock_charger()
    await setup_integration(hass, config_entry)

    state = hass.states.get("sensor.voltie_charger_4335_toltott_energia")
    assert state is not None
    assert state.name == "Voltie Charger 4335 Töltött energia"
    assert (
        hass.states.get("number.voltie_charger_4335_epuletaram_korlat").name
        == "Voltie Charger 4335 Épületáram-korlát"
    )


# ---- number: dynamic upper bound from current_hw_limit ----


@pytest.mark.parametrize(
    ("hw_limit", "expected_max"),
    [
        (32, 32.0),
        (16, 16.0),
        # The API caps conf_current_limit at 32 A whatever the hardware says.
        (63, 32.0),
        (None, 32.0),  # absent -> static spec bound
        ("nonsense", 32.0),  # wrong type -> static spec bound
        (3, 32.0),  # below the 6 A floor is nonsensical -> static bound
    ],
)
async def test_current_limit_max_follows_hardware(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    hw_limit: Any,
    expected_max: float,
) -> None:
    """number.current_limit's ceiling comes from the charger (ticket section 1)."""
    status = status_payload()
    if hw_limit is None:
        status.pop("current_hw_limit")
    else:
        status["current_hw_limit"] = hw_limit
    mock_charger(status=status)
    await setup_integration(hass, config_entry)

    state = hass.states.get(_eid("number", "maximum_charging_current"))
    assert state.attributes["max"] == expected_max
    assert state.attributes["min"] == 6.0


async def test_new_config_numbers_exposed(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """All eight numeric /config keys become entities with spec bounds."""
    mock_charger()
    await setup_integration(hass, config_entry)

    expected = {
        "building_current_limit": (16.0, 6.0, 200.0),
        "eco_mode_start_current": (3.0, 1.0, 5.0),
        "grid_control_stop_voltage": (230.0, 200.0, 300.0),
        "grid_control_minimum_voltage": (235.0, 200.0, 300.0),
        "grid_control_maximum_voltage": (245.0, 200.0, 300.0),
        "grid_control_increase_delay": (30.0, 0.0, 300.0),
        "grid_control_decrease_delay": (30.0, 0.0, 300.0),
    }
    for slug, (value, minimum, maximum) in expected.items():
        state = hass.states.get(_eid("number", slug))
        assert state is not None, f"missing number.{PREFIX}_{slug}"
        assert float(state.state) == value, slug
        assert state.attributes["min"] == minimum, slug
        assert state.attributes["max"] == maximum, slug


async def test_building_current_limit_goes_to_200_a(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """3x40 A and 3x63 A supplies are common, so 32 A was too low (VLT-2890).

    The mobile app can already store values like 130 A, which must read back
    as a normal in-range value.
    """
    mock_charger(config=config_payload(conf_dlm_current_limit=130))
    await setup_integration(hass, config_entry)
    eid = _eid("number", "building_current_limit")
    state = hass.states.get(eid)
    assert float(state.state) == 130.0
    assert state.attributes["max"] == 200.0

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: eid, "value": 200},
        blocking=True,
    )
    put = [c for c in aioclient_mock.mock_calls if c[0] == "PUT"][-1]
    assert put[2] == {"conf_dlm_current_limit": 200}


async def test_building_current_limit_refused_by_older_firmware(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Firmware still capping it at 32 A drops 63 A; the error must say why."""
    mock_charger()
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.put(f"{BASE}/config", json=ack(accepted=0))

    with pytest.raises(HomeAssistantError, match="outside the range"):
        await hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: _eid("number", "building_current_limit"), "value": 63},
            blocking=True,
        )


async def test_config_entities_unavailable_on_legacy_firmware(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """Keys absent from /config gate their entities, per the existing pattern."""
    mock_charger(config=legacy_config_payload(), rfid_supported=False)
    await setup_integration(hass, config_entry)

    assert (
        hass.states.get(_eid("number", "building_current_limit")).state
        == STATE_UNAVAILABLE
    )
    assert hass.states.get(_eid("select", "load_management_mode")).state == (
        STATE_UNAVAILABLE
    )
    assert hass.states.get(_eid("switch", "out_of_service")).state == STATE_UNAVAILABLE
    # The original keys still work.
    assert (
        float(hass.states.get(_eid("number", "maximum_charging_current")).state) == 16.0
    )


# ---- select ----


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "off"), (1, "dynamic"), (2, "eco"), (3, "green"), (4, "grid_control")],
)
async def test_dlm_mode_options(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    value: int,
    expected: str,
) -> None:
    mock_charger(config=config_payload(conf_dlm_mode=value))
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("select", "load_management_mode")).state == expected


async def test_dlm_mode_unknown_value_reads_unknown(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """A mode a future firmware adds must not raise or spam the log."""
    mock_charger(config=config_payload(conf_dlm_mode=9))
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("select", "load_management_mode")).state == "unknown"


async def test_access_mode_select_writes_int(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    await hass.services.async_call(
        "select",
        "select_option",
        {
            ATTR_ENTITY_ID: _eid("select", "access_mode"),
            "option": "home_charger_rfid",
        },
        blocking=True,
    )
    put = [c for c in aioclient_mock.mock_calls if c[0] == "PUT"][-1]
    assert put[2] == {"conf_access_mode": 1}


# ---- switch: conf_force_single_phase ----


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, STATE_OFF), (1, STATE_ON), (3, "unknown")],
)
async def test_force_single_phase_states(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    value: int,
    expected: str,
) -> None:
    mock_charger(config=config_payload(conf_force_single_phase=value))
    await setup_integration(hass, config_entry)
    assert (
        hass.states.get(_eid("switch", "force_single_phase_charging")).state == expected
    )


async def test_force_single_phase_unavailable_when_not_supported(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """Value 2 means the hardware cannot do it (spec 4.7)."""
    mock_charger(config=config_payload(conf_force_single_phase=2))
    await setup_integration(hass, config_entry)
    assert (
        hass.states.get(_eid("switch", "force_single_phase_charging")).state
        == STATE_UNAVAILABLE
    )


async def test_force_single_phase_writes_only_zero_or_one(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """2 and 3 are status values that must never be written back."""
    mock_charger(config=config_payload(conf_force_single_phase=3))
    await setup_integration(hass, config_entry)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: _eid("switch", "force_single_phase_charging")},
        blocking=True,
    )
    put = [c for c in aioclient_mock.mock_calls if c[0] == "PUT"][-1]
    assert put[2] == {"conf_force_single_phase": 1}


async def test_out_of_service_polarity(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """true means out of service; the switch must not invert it."""
    mock_charger(config=config_payload(conf_out_of_service=True))
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("switch", "out_of_service")).state == STATE_ON

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: _eid("switch", "out_of_service")},
        blocking=True,
    )
    put = [c for c in aioclient_mock.mock_calls if c[0] == "PUT"][-1]
    assert put[2] == {"conf_out_of_service": False}


async def test_rejected_config_write_raises(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A silently-dropped parameter must surface as an error to the user."""
    mock_charger()
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.put(f"{BASE}/config", json=ack(accepted=0))

    with pytest.raises(HomeAssistantError, match="rejected"):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: _eid("switch", "force_single_phase_charging")},
            blocking=True,
        )


# ---- RFID entities ----


async def test_rfid_entities_present_on_v5(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    assert hass.states.get(_eid("sensor", "rfid_tags_stored")).state == "5"
    assert hass.states.get(_eid("sensor", "rfid_learn_time_remaining")).state == "0"
    assert hass.states.get(_eid("binary_sensor", "rfid_reader_enabled")).state == (
        STATE_ON
    )
    assert hass.states.get(_eid("binary_sensor", "rfid_reader_working")).state == (
        STATE_ON
    )
    assert hass.states.get(_eid("binary_sensor", "rfid_learn_mode")).state == STATE_OFF
    assert hass.states.get(_eid("button", "start_rfid_learn_mode")) is not None
    assert hass.states.get(_eid("button", "cancel_rfid_learn_mode")) is not None


async def test_rfid_entities_absent_on_pre_v5(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """Old firmware must not get a pile of permanently-unavailable entities."""
    mock_charger(rfid_supported=False, apiver=4, config=legacy_config_payload())
    await setup_integration(hass, config_entry)

    registry = er.async_get(hass)
    rfid_entities = [
        e.entity_id
        for e in registry.entities.values()
        if e.config_entry_id == config_entry.entry_id and "rfid" in e.unique_id
    ]
    assert rfid_entities == []
    # The reboot button is still offered: /extras predates v5.
    assert hass.states.get(_eid("button", "reboot_charger")) is not None


async def test_rfid_learn_state_reflected(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger(
        rfid_status=rfid_status_payload(learn_in_progress=True, learn_to_sec=25)
    )
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("binary_sensor", "rfid_learn_mode")).state == STATE_ON
    assert hass.states.get(_eid("sensor", "rfid_learn_time_remaining")).state == "25"


# ---- buttons ----


async def test_reboot_button(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: _eid("button", "reboot_charger")},
        blocking=True,
    )
    post = [c for c in aioclient_mock.mock_calls if c[0] == "POST"][-1]
    assert post[2] == {"command": "charger_reboot"}


async def test_rfid_learn_buttons(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: _eid("button", "start_rfid_learn_mode")},
        blocking=True,
    )
    assert aioclient_mock.mock_calls[-1][2] == {"command": "rfid_learn"} or any(
        c[2] == {"command": "rfid_learn"} for c in aioclient_mock.mock_calls
    )

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: _eid("button", "cancel_rfid_learn_mode")},
        blocking=True,
    )
    assert any(
        c[2] == {"command": "rfid_learn_cancel"} for c in aioclient_mock.mock_calls
    )


async def test_reboot_button_unsupported_firmware(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """error_code 24 must become an actionable 'update your firmware' error."""
    mock_charger()
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/extras", json=ack(error_code=24))

    with pytest.raises(HomeAssistantError, match="firmware"):
        await hass.services.async_call(
            "button",
            "press",
            {ATTR_ENTITY_ID: _eid("button", "reboot_charger")},
            blocking=True,
        )


# ---- device info ----


async def test_device_info(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, device_registry
) -> None:
    """configuration_url carries the port and versions are formatted (VLT-2120)."""
    mock_charger(status=status_payload(sw_ver=1003025, fw_ver=105))
    await setup_integration(hass, config_entry)

    device = charger_device(device_registry, config_entry)
    assert device.configuration_url == "http://192.168.1.234:5059"
    assert device.sw_version == "1.3.25 (EVSE 1.05)"
    assert device.hw_version is None
    assert device.serial_number == "000000009d104335"


# ---- alignment with the built-in integration (v0.5.0) ----

# Every entity key, per platform. The built-in integration uses the same ones,
# and its unique IDs are "{charger_id}_{key}", so these must never change.
FROZEN_KEYS: dict[str, set[str]] = {
    "sensor": {
        "evse_state",
        "charge_power",
        "charge_current",
        "session_energy",
        "total_energy",
        "mains_voltage",
        "phases",
        "phases_used",
        "current_offered",
        "session_charge_time",
        "session_idle_time",
        "average_power",
        "current_hw_limit",
        *(
            f"{kind}_l{phase}"
            for kind in ("voltage", "current", "power", "dlm_current", "ipm_current")
            for phase in (1, 2, 3)
        ),
        "rfid_list_count",
        "rfid_learn_remaining",
        "rfid_list_capacity",
    },
    "binary_sensor": {
        "car_connected",
        "is_charging",
        "problem",
        "dlm_valid",
        "ipm_valid",
        "rfid_reader_enabled",
        "rfid_reader_working",
        "rfid_learn_in_progress",
    },
    "switch": {
        "charging",
        "autostart",
        "display",
        "front_led",
        "rear_led",
        "buzzer",
        "out_of_service",
        "force_single_phase",
    },
    "number": {
        "current_limit",
        "dlm_current_limit",
        "dlm_eco_startcurr",
        "grid_u_stop",
        "grid_u_min",
        "grid_u_max",
        "grid_t_up",
        "grid_t_dn",
    },
    "select": {"dlm_mode", "access_mode"},
    "button": {"reboot", "rfid_learn", "rfid_learn_cancel"},
    "event": {"charging_session"},
}


async def test_entity_keys_are_frozen(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_charger(status=status_payload(meter_kwh=1523.4))
    await setup_integration(hass, config_entry)

    keys: dict[str, set[str]] = {}
    for entry in er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    ):
        assert entry.unique_id.startswith(f"{CHARGER_ID}_"), entry.unique_id
        keys.setdefault(entry.domain, set()).add(
            entry.unique_id.removeprefix(f"{CHARGER_ID}_")
        )
    assert keys == FROZEN_KEYS


@pytest.mark.parametrize(
    ("entity_id", "category", "enabled"),
    [
        (_eid("sensor", "evse_state"), None, True),
        (_eid("sensor", "mains_voltage"), EntityCategory.DIAGNOSTIC, True),
        (_eid("sensor", "phases_wired"), EntityCategory.DIAGNOSTIC, True),
        (_eid("sensor", "voltage_l1"), EntityCategory.DIAGNOSTIC, False),
        (_eid("sensor", "current_l2"), EntityCategory.DIAGNOSTIC, False),
        (_eid("sensor", "power_l3"), EntityCategory.DIAGNOSTIC, False),
        (_eid("button", "start_rfid_learn_mode"), EntityCategory.CONFIG, True),
        (_eid("button", "cancel_rfid_learn_mode"), EntityCategory.CONFIG, True),
    ],
)
async def test_entity_metadata_matches_the_builtin_integration(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    entity_id: str,
    category: EntityCategory | None,
    enabled: bool,
) -> None:
    """Categories and enabled-by-default as in the built-in integration.

    On a new install, that is: an existing registry entry keeps whatever
    enabled state it has.
    """
    mock_charger()
    await setup_integration(hass, config_entry)
    entry = entity_registry.async_get(entity_id)
    assert entry is not None, entity_id
    assert entry.entity_category == category
    assert (entry.disabled_by is None) is enabled


async def test_existing_per_phase_sensor_stays_enabled(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Disabled by default only applies to entities created from now on."""
    mock_charger()
    config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"voltie_charger_voltage_l1_{CHARGER_ID}",
        config_entry=config_entry,
        suggested_object_id=f"{PREFIX}_voltage_l1",
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entry = entity_registry.async_get(_eid("sensor", "voltage_l1"))
    assert entry.unique_id == f"{CHARGER_ID}_voltage_l1"
    assert entry.disabled_by is None
    assert entry.entity_category == EntityCategory.DIAGNOSTIC
    assert float(hass.states.get(entry.entity_id).state) == 231.461


@pytest.mark.parametrize(
    ("key", "name"),
    [("problem", "Problem"), ("charging", "Charging")],
)
async def test_named_after_the_device_class(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    key: str,
    name: str,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    entity_id = _eid("binary_sensor", key)
    assert entity_registry.async_get(entity_id).translation_key is None
    assert hass.states.get(entity_id).name == f"Voltie Charger 4335 {name}"


async def test_no_extra_state_attributes(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """raw_code, session_start, periods and error are gone, as in core."""
    mock_charger(
        status=status_payload(
            evse_state=6, is_car_connected=True, cdr=cdr_payload()
        )
    )
    await setup_integration(hass, config_entry)

    evse_state = hass.states.get(_eid("sensor", "evse_state"))
    assert evse_state.state == "gfci_fault"
    assert "raw_code" not in evse_state.attributes
    energy = hass.states.get(_eid("sensor", "session_energy"))
    assert float(energy.state) == 5.852
    assert "session_start" not in energy.attributes
    assert "periods" not in energy.attributes
    problem = hass.states.get(_eid("binary_sensor", "problem"))
    assert problem.state == STATE_ON
    assert set(problem.attributes) == {"device_class", "friendly_name"}
