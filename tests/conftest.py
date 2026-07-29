"""Shared fixtures for the Voltie Charger tests.

Payloads mirror the examples in the Voltie HTTP API v5.0 R3 specification so a
drift between the spec and the integration shows up as a test failure.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant

from custom_components.voltie_charger.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

HOST = "192.168.1.234"
PORT = 5059
CHARGER_ID = "000000009d104335"
BASE = f"http://{HOST}:{PORT}"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom component importable in every test."""
    return


@pytest.fixture(autouse=True)
def mock_zeroconf_dependency(mock_async_zeroconf):
    """The integration depends on zeroconf, which would open a real socket."""
    return


@pytest.fixture(autouse=True)
def no_retry_backoff():
    """Drop the retry sleep so a failing poll settles within the test's tick.

    The coordinator's real backoff is a wall-clock sleep that freezegun does
    not fast-forward, which would otherwise leave updates in flight.
    """
    with patch(
        "custom_components.voltie_charger.UPDATE_RETRY_BACKOFF_S", 0
    ):
        yield


def status_payload(**overrides: Any) -> dict[str, Any]:
    """A /status response (spec 4.2)."""
    payload: dict[str, Any] = {
        "charger_id": CHARGER_ID,
        "system_time": 1708335549,
        "sw_ver": 1003025,
        "fw_ver": 199,
        "evse_state": 1,
        "is_car_connected": False,
        "charge_enabled": True,
        "is_charging": False,
        "autostart": False,
        "mains_voltage": 233,
        "phases": 3,
        "phases_used": 0,
        "current_hw_limit": 32,
        "current_offered": 32,
        "charge_current": 0,
        "charge_power": 0,
        "first_cdr": 1,
        "last_cdr": 445,
        "cdr": None,
        "response_time_ms": 0,
        "error_code": 0,
    }
    payload.update(overrides)
    return payload


def power_payload(**overrides: Any) -> dict[str, Any]:
    """A /power response (spec 4.9)."""
    stat = {
        "current1": 0,
        "current2": 0,
        "current3": 0,
        "power1": 0,
        "power2": 0,
        "power3": 0,
        "voltage1": 231.461,
        "voltage2": 0,
        "voltage3": 0,
        "dlm_valid": True,
        "dlm_current1": -14.186,
        "dlm_current2": -22.042,
        "dlm_current3": -23.688,
        "ipm_valid": False,
        "ipm_current1": 0,
        "ipm_current2": 0,
        "ipm_current3": 0,
    }
    stat.update(overrides)
    return {"power_stat": stat, "response_time_ms": 15, "error_code": 0}


def config_payload(**overrides: Any) -> dict[str, Any]:
    """A GET /config response with the full v5.0 key set (spec 4.7)."""
    payload: dict[str, Any] = {
        "conf_autostart_enabled": True,
        "conf_current_limit": 16,
        "conf_disp_enabled": True,
        "conf_front_led_enabled": True,
        "conf_rear_led_enabled": True,
        "conf_buzzer_enabled": True,
        "conf_force_single_phase": 0,
        "conf_dlm_mode": 1,
        "conf_dlm_current_limit": 16,
        "conf_dlm_eco_startcurr": 3,
        "conf_grid_u_stop": 230,
        "conf_grid_u_min": 235,
        "conf_grid_u_max": 245,
        "conf_grid_t_up": 30,
        "conf_grid_t_dn": 30,
        "conf_out_of_service": False,
        "conf_access_mode": 0,
        "response_time_ms": 0,
        "error_code": 0,
    }
    payload.update(overrides)
    return payload


def legacy_config_payload() -> dict[str, Any]:
    """A pre-v5 /config response: only the six original keys."""
    return {
        "conf_autostart_enabled": True,
        "conf_current_limit": 16,
        "conf_disp_enabled": True,
        "conf_front_led_enabled": True,
        "conf_rear_led_enabled": True,
        "conf_buzzer_enabled": True,
        "response_time_ms": 0,
        "error_code": 0,
    }


def rfid_status_payload(**overrides: Any) -> dict[str, Any]:
    """A GET /rfid/status response (spec 4.11.2) — fields nested."""
    status = {
        "list_count": 5,
        "list_capacity": 200,
        "list_format_ver": 3,
        "list_hash": "A3F21B8C",
        "reader_enabled": True,
        "reader_working": True,
        "learn_in_progress": False,
        "learn_to_sec": 0,
    }
    status.update(overrides)
    return {"rfid_status": status, "response_time_ms": 0, "error_code": 0}


def rfid_list_payload() -> dict[str, Any]:
    """A GET /rfid response (spec 4.11.1)."""
    return {
        "rfid_list": [
            {
                "id": "0A1B2C3D",
                "name": "John Doe",
                "last_use": 1708336326,
                "enabled": True,
                "comment": "note",
            },
            {
                "id": "1122334455",
                "name": "Spare",
                "last_use": 0,
                "enabled": False,
                "comment": "",
            },
        ],
        "rfid_count": 2,
        "list_hash": "A3F21B8C",
        "response_time_ms": 0,
        "error_code": 0,
    }


def ack(**overrides: Any) -> dict[str, Any]:
    """A command acknowledgement (spec section 3)."""
    payload = {"response_time_ms": 0, "error_code": 0}
    payload.update(overrides)
    return payload


@pytest.fixture
def mock_charger(
    aioclient_mock: AiohttpClientMocker,
) -> Callable[..., AiohttpClientMocker]:
    """Register a full API v5 charger, with hooks to vary each endpoint."""

    def _setup(
        *,
        status: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        rfid_status: dict[str, Any] | None = None,
        rfid_supported: bool = True,
        apiver: int | None = 5,
    ) -> AiohttpClientMocker:
        # The mocker resolves the FIRST matching registration, so a test that
        # wants one endpoint to fail registers that itself before calling this.
        aioclient_mock.get(f"{BASE}/status", json=status or status_payload())
        aioclient_mock.get(f"{BASE}/power", json=power_payload())
        aioclient_mock.get(f"{BASE}/config", json=config or config_payload())
        aioclient_mock.put(f"{BASE}/config", json=ack(accepted=1))
        aioclient_mock.get(f"{BASE}/start", json=ack(cdr_id=629))
        aioclient_mock.get(f"{BASE}/stop", json=ack())
        aioclient_mock.post(f"{BASE}/extras", json=ack())

        if apiver is None:
            aioclient_mock.get(f"{BASE}/apiver", status=404)
        else:
            aioclient_mock.get(
                f"{BASE}/apiver", json={"api_files_version": apiver}
            )

        if rfid_supported:
            aioclient_mock.get(
                f"{BASE}/rfid/status", json=rfid_status or rfid_status_payload()
            )
            aioclient_mock.get(f"{BASE}/rfid", json=rfid_list_payload())
            aioclient_mock.post(f"{BASE}/rfid", json=ack())
            aioclient_mock.put(f"{BASE}/rfid", json=ack())
            aioclient_mock.delete(f"{BASE}/rfid", json=ack())
            aioclient_mock.post(f"{BASE}/rfid/extras", json=ack())
        else:
            # Pre-v5 firmware does not implement the endpoint at all.
            aioclient_mock.get(f"{BASE}/rfid/status", status=404)
            aioclient_mock.get(f"{BASE}/rfid", status=404)
            aioclient_mock.post(f"{BASE}/rfid/extras", status=404)

        return aioclient_mock

    return _setup


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry pointing at the mocked charger."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Voltie Charger ({HOST})",
        unique_id=CHARGER_ID,
        data={
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_USERNAME: "",
            CONF_PASSWORD: "",
        },
    )


async def setup_integration(
    hass: HomeAssistant, entry: MockConfigEntry
) -> MockConfigEntry:
    """Add and set up the config entry, waiting for platforms to finish."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
