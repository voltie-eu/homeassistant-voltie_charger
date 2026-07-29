"""Entity behaviour tests, including the API v5 additions."""
from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.voltie_charger.const import DOMAIN

from .conftest import (
    BASE,
    ack,
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
    """0 is a real value, not 'unknown' — an enum sensor would have logged.

    Named "Active phases" rather than "Phases in use": on an upgraded install the
    pre-existing `phases` sensor already owns the `..._phases_in_use` entity_id,
    so reusing that name produced two entities whose ids differed only by an area
    prefix.
    """
    mock_charger(status=status_payload(phases_used=0))
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("sensor", "active_phases")).state == "0"


async def test_api_version_sensor(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger(apiver=5)
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("sensor", "api_version")).state == "5"


async def test_api_version_absent_on_old_firmware(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """A 404 on /apiver must not break setup."""
    mock_charger(apiver=None, rfid_supported=False)
    await setup_integration(hass, config_entry)
    assert config_entry.state.name == "LOADED"
    assert hass.states.get(_eid("sensor", "api_version")).state == "unknown"


async def test_evse_state_4_is_not_an_error(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """State 4 is obsolete but documented as a charging state (spec 5.1)."""
    mock_charger(status=status_payload(evse_state=4))
    await setup_integration(hass, config_entry)
    state = hass.states.get(_eid("sensor", "evse_state"))
    assert state.state == "ev_connected_charging_ventilation"


async def test_undocumented_evse_state_is_error(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger(status=status_payload(evse_state=99))
    await setup_integration(hass, config_entry)
    assert hass.states.get(_eid("sensor", "evse_state")).state == "error"


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
        "building_current_limit": (16.0, 6.0, 32.0),
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


async def test_rfid_list_hash_is_a_string_sensor(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, entity_registry
) -> None:
    """The hash is hex text; treating it as numeric would break the recorder."""
    mock_charger()
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"voltie_charger_rfid_list_hash_{config_entry.entry_id}",
        suggested_object_id=f"{PREFIX}_rfid_list_hash",
        disabled_by=None,
    )
    await setup_integration(hass, config_entry)
    state = hass.states.get(_eid("sensor", "rfid_list_hash"))
    assert state.state == "A3F21B8C"
    assert "state_class" not in state.attributes


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

    device = device_registry.async_get_device(
        identifiers={(DOMAIN, "000000009d104335")}
    )
    assert device.configuration_url == "http://192.168.1.234:5059"
    assert device.sw_version == "1.3.25 (EVSE 1.05)"
    assert device.hw_version is None
    assert device.serial_number == "000000009d104335"
