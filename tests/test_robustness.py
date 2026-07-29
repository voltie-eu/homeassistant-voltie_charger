"""Robustness: services on an unloaded entry, dynamic bounds, and log hygiene."""
from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.voltie_charger.const import DEFAULT_SCAN_INTERVAL, DOMAIN

from .conftest import BASE, setup_integration, status_payload

PREFIX = "voltie_charger_4335"


def _own_errors(caplog) -> list[str]:
    """ERROR records emitted by this integration (not HA's own machinery)."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelname == "ERROR"
        and r.name.startswith("custom_components.voltie_charger")
    ]


def _bare_client(hass):
    """A client with no config entry, for exercising raw response handling."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.voltie_charger.client import VoltieChargerClient

    from .conftest import HOST, PORT

    return VoltieChargerClient(async_get_clientsession(hass), HOST, port=PORT)


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("display_text", {"message": "hi"}),
        ("set_rear_led", {"brightness": 0.5, "color_rgb": "#FFFFFF"}),
        ("start_charging", {}),
        ("add_rfid_tag", {"id": "0A1B2C3D"}),
        ("modify_rfid_tag", {"id": "0A1B2C3D", "enabled": True}),
        ("delete_rfid_tag", {"id": "0A1B2C3D"}),
        ("start_rfid_learn", {}),
    ],
)
async def test_service_on_unloaded_entry_is_clean(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    device_registry,
    service: str,
    data: dict,
) -> None:
    """After unload, runtime_data is gone: must be a clean error, not AttributeError."""
    mock_charger()
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, "000000009d104335")}
    )
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="not set up"):
        await hass.services.async_call(
            DOMAIN, service, {"device_id": device.id, **data}, blocking=True
        )


async def test_list_rfid_tags_on_unloaded_entry(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, device_registry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, "000000009d104335")}
    )
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "list_rfid_tags",
            {"device_id": device.id},
            blocking=True,
            return_response=True,
        )


async def test_dynamic_max_follows_a_mid_run_change(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """native_max_value overrides a cached_property via super() — prove no staleness."""
    mock_charger(status=status_payload(current_hw_limit=32))
    await setup_integration(hass, config_entry)
    eid = f"number.{PREFIX}_maximum_charging_current"
    assert hass.states.get(eid).attributes["max"] == 32.0

    aioclient_mock.clear_requests()
    mock_charger(status=status_payload(current_hw_limit=16))
    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(eid).attributes["max"] == 16.0, "stale cached max"


async def test_no_error_logs_on_a_normal_poll(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, caplog
) -> None:
    """A healthy v5 charger must produce no WARNING/ERROR from this integration."""
    mock_charger()
    await setup_integration(hass, config_entry)
    bad = [
        r
        for r in caplog.records
        if r.levelname in ("ERROR", "WARNING")
        and r.name.startswith("custom_components.voltie_charger")
    ]
    assert not bad, [r.getMessage() for r in bad]


async def test_no_error_logs_on_legacy_firmware(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, caplog
) -> None:
    """Pre-v5 firmware may log at most one informative warning, not a storm."""
    from .conftest import legacy_config_payload

    mock_charger(rfid_supported=False, apiver=4, config=legacy_config_payload())
    await setup_integration(hass, config_entry)
    own = [
        r
        for r in caplog.records
        if r.name.startswith("custom_components.voltie_charger")
    ]
    assert not [r for r in own if r.levelname == "ERROR"], [
        r.getMessage() for r in own
    ]
    # Exactly one warning, naming the cause, and only once — the latch must stop
    # it repeating on every poll.
    warns = [r.getMessage() for r in own if r.levelname == "WARNING"]
    assert len(warns) == 1, warns
    assert "API v5" in warns[0]


# ---- malformed payload guards (found by adversarial review) ----


@pytest.mark.parametrize(
    "bad_status",
    [
        {"phases": 3.0},
        {"phases": True},
        {"phases_used": "three"},
        {"current_hw_limit": True},
        {"current_hw_limit": "32"},
        {"evse_state": {"code": 3}},
        {"evse_state": [3]},
        {"evse_state": "3"},
    ],
)
async def test_malformed_status_fields_do_not_break_the_poll(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    caplog,
    bad_status: dict,
) -> None:
    """A junk field must read as unknown, never raise.

    An exception in a value_fn escapes the coordinator's listener dispatch and
    stops every entity after it from updating.
    """
    mock_charger(status=status_payload(**bad_status))
    await setup_integration(hass, config_entry)

    assert not _own_errors(caplog)
    # Entities that do not depend on the bad field still carry real values.
    assert hass.states.get(f"sensor.{PREFIX}_charge_power").state == "0"
    assert hass.states.get(f"sensor.{PREFIX}_mains_voltage").state == "233"


async def test_non_dict_power_stat_does_not_break_per_phase_sensors(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog,
) -> None:
    """power_stat as a list would make .get() raise in 15 value_fns."""
    aioclient_mock.get(
        f"{BASE}/power", json={"power_stat": [1, 2, 3], "error_code": 0}
    )
    mock_charger()
    await setup_integration(hass, config_entry)

    assert hass.states.get(f"sensor.{PREFIX}_voltage_l1").state == "unknown"
    assert not _own_errors(caplog)


@pytest.mark.parametrize(
    "bad_rfid",
    [{"list_count": "five"}, {"learn_to_sec": None}, {"list_hash": 12345}],
)
async def test_malformed_rfid_status_does_not_break_the_poll(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    caplog,
    bad_rfid: dict,
) -> None:
    from .conftest import rfid_status_payload

    mock_charger(rfid_status=rfid_status_payload(**bad_rfid))
    await setup_integration(hass, config_entry)
    assert not _own_errors(caplog)
    assert hass.states.get(f"sensor.{PREFIX}_charge_power").state == "0"


@pytest.mark.parametrize("bad_code", ["OK", [1], {"a": 1}, True])
async def test_non_numeric_error_code_stays_inside_the_error_hierarchy(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, bad_code
) -> None:
    """A bare ValueError would bypass retries, latches and error translation."""
    from custom_components.voltie_charger.client import VoltieChargerError

    aioclient_mock.get(
        f"{BASE}/status", json={"charger_id": "abc", "error_code": bad_code}
    )
    with pytest.raises(VoltieChargerError):
        await _bare_client(hass).async_get_status()


async def test_string_zero_error_code_is_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A "0" means OK; comparing it to the int 0 would fail every request."""
    aioclient_mock.get(
        f"{BASE}/status", json={"charger_id": "abc", "error_code": "0"}
    )
    assert (await _bare_client(hass).async_get_status())["charger_id"] == "abc"


async def test_config_write_is_reflected_immediately(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A burst of writes must not leave later entities showing stale values.

    async_request_refresh is debounced: the first write's refresh runs at once,
    but a second write inside the cooldown gets no refresh, so without the
    optimistic update it would keep showing its pre-write value. The mocked
    /config deliberately keeps reporting the old numbers, so the value asserted
    below can only come from the optimistic update.
    """
    mock_charger()
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    mock_charger()

    # First write: consumes the debouncer's immediate slot.
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": f"number.{PREFIX}_maximum_charging_current", "value": 10},
        blocking=True,
    )
    # Second write, inside the cooldown: no refresh will run for it.
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": f"number.{PREFIX}_building_current_limit", "value": 20},
        blocking=True,
    )

    building = hass.states.get(f"number.{PREFIX}_building_current_limit")
    assert float(building.state) == 20.0, (
        "debounced write fell back to the charger's stale /config value"
    )


async def test_write_auth_failure_is_actionable(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The auth branch in each platform's error mapper must be reachable."""
    from homeassistant.exceptions import HomeAssistantError

    mock_charger()
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.put(f"{BASE}/config", status=401)
    mock_charger()

    with pytest.raises(HomeAssistantError, match="Authentication failed"):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": f"switch.{PREFIX}_buzzer"},
            blocking=True,
        )


async def test_yaml_configuration_is_rejected(hass: HomeAssistant, caplog) -> None:
    """Without CONFIG_SCHEMA a stray YAML block is silently swallowed."""
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, DOMAIN, {DOMAIN: {"host": "1.2.3.4"}})
    assert "does not support YAML setup" in caplog.text


async def test_list_rfid_tags_response_is_self_consistent(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry,
) -> None:
    """count must never exceed the tags actually returned."""
    mock_charger()
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, "000000009d104335")}
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/rfid",
        json={"rfid_list": {"0": {"id": "x"}}, "rfid_count": 1, "error_code": 0},
    )
    mock_charger()

    response = await hass.services.async_call(
        DOMAIN,
        "list_rfid_tags",
        {"device_id": device.id},
        blocking=True,
        return_response=True,
    )
    assert response["count"] == len(response["tags"]) == 0
