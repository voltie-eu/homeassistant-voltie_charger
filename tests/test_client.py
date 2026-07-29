"""Tests for the HTTP client's response and error handling."""
from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.voltie_charger.client import (
    VoltieChargerAuthError,
    VoltieChargerClient,
    VoltieChargerConnectionError,
    VoltieChargerRejectedError,
    VoltieChargerUnsupportedError,
)

from .conftest import BASE, HOST, PORT, ack


def _client(hass: HomeAssistant) -> VoltieChargerClient:
    return VoltieChargerClient(async_get_clientsession(hass), HOST, port=PORT)


async def test_port_is_used_in_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A non-default port must appear in the request URL."""
    aioclient_mock.get("http://192.168.1.234:8080/status", json=ack())
    client = VoltieChargerClient(async_get_clientsession(hass), HOST, port=8080)
    await client.async_get_status()
    assert client.port == 8080


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int
) -> None:
    """401 and 403 both mean the credentials are the problem."""
    aioclient_mock.get(f"{BASE}/status", status=status)
    with pytest.raises(VoltieChargerAuthError):
        await _client(hass).async_get_status()


@pytest.mark.parametrize("status", [404, 405])
async def test_missing_endpoint_is_unsupported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int
) -> None:
    """A missing endpoint means old firmware, not a network fault."""
    aioclient_mock.get(f"{BASE}/rfid/status", status=status)
    with pytest.raises(VoltieChargerUnsupportedError):
        await _client(hass).async_get_rfid_status()


async def test_server_error_is_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """5xx is transient and must stay retryable."""
    aioclient_mock.get(f"{BASE}/status", status=500)
    with pytest.raises(VoltieChargerConnectionError):
        await _client(hass).async_get_status()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (1, VoltieChargerRejectedError),
        (5, VoltieChargerRejectedError),
        # 23 is a cluster-topology problem on current firmware, not a
        # missing feature, so it must NOT be classed as unsupported.
        (23, VoltieChargerRejectedError),
        (24, VoltieChargerUnsupportedError),
    ],
)
async def test_error_code_mapping(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    code: int,
    expected: type[Exception],
) -> None:
    """error_code 23/24 mean 'this firmware cannot', 5/1 mean 'rejected'."""
    aioclient_mock.post(f"{BASE}/extras", json=ack(error_code=code))
    with pytest.raises(expected):
        await _client(hass).async_reboot()


async def test_internal_status_string_is_transient(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """{"status": "internal timeout"} (spec section 3) must be retryable."""
    aioclient_mock.get(f"{BASE}/status", json={"status": "internal timeout"})
    with pytest.raises(VoltieChargerConnectionError, match="internal timeout"):
        await _client(hass).async_get_status()


async def test_status_field_alongside_error_code_is_not_an_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A normal payload that grows a 'status' key must not fail the poll.

    This is the VLT-2120 M3 regression guard: the status-string check is only
    trusted when error_code is absent entirely.
    """
    aioclient_mock.get(
        f"{BASE}/status",
        json={"charger_id": "abc", "status": "charging", "error_code": 0},
    )
    result = await _client(hass).async_get_status()
    assert result["charger_id"] == "abc"


async def test_non_json_response(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/status", text="<html>nope</html>")
    with pytest.raises(VoltieChargerConnectionError):
        await _client(hass).async_get_status()


async def test_config_partial_accept_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A silently-dropped parameter must surface, not look like success."""
    aioclient_mock.put(f"{BASE}/config", json=ack(accepted=1))
    with pytest.raises(VoltieChargerRejectedError, match="only 1/2"):
        await _client(hass).async_set_config(
            {"conf_current_limit": 16, "conf_dlm_mode": 1}
        )


async def test_apiver(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/apiver", json={"api_files_version": 5})
    assert await _client(hass).async_get_apiver() == 5


async def test_apiver_missing_field(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/apiver", json=ack())
    assert await _client(hass).async_get_apiver() is None


async def test_rfid_status_requires_nested_block(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The spec nests the fields under rfid_status; a flat body is unusable."""
    aioclient_mock.get(f"{BASE}/rfid/status", json=ack(list_count=5))
    with pytest.raises(VoltieChargerConnectionError, match="rfid_status"):
        await _client(hass).async_get_rfid_status()


async def test_extras_command_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """/extras takes {"command":..., "params":...} and omits empty params."""
    aioclient_mock.post(f"{BASE}/extras", json=ack())
    client = _client(hass)

    await client.async_display_scroll_text("hi", repeat_count=3, clear_first=True)
    assert aioclient_mock.mock_calls[-1][2] == {
        "command": "display_scroll_text",
        "params": {"message": "hi", "repeat_count": 3, "clear_first": True},
    }

    await client.async_display_scroll_text("hi")
    assert aioclient_mock.mock_calls[-1][2] == {
        "command": "display_scroll_text",
        "params": {"message": "hi"},
    }

    await client.async_reboot()
    assert aioclient_mock.mock_calls[-1][2] == {"command": "charger_reboot"}

    await client.async_set_rear_led(brightness=0.5, color_rgb="#FF8800")
    assert aioclient_mock.mock_calls[-1][2] == {
        "command": "rear_led_set",
        "params": {"brightness": 0.5, "color_rgb": "#FF8800"},
    }


async def test_rfid_modify_omits_unset_fields(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """PUT treats absent fields as 'unchanged', so unset args must not be sent."""
    aioclient_mock.put(f"{BASE}/rfid", json=ack())
    await _client(hass).async_modify_rfid_tag("0A1B2C3D", enabled=False)
    assert aioclient_mock.mock_calls[-1][2] == {"id": "0A1B2C3D", "enabled": False}


async def test_rfid_add_includes_given_fields(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/rfid", json=ack())
    await _client(hass).async_add_rfid_tag(
        "0A1B2C3D", name="John", enabled=True, comment="note"
    )
    assert aioclient_mock.mock_calls[-1][2] == {
        "id": "0A1B2C3D",
        "name": "John",
        "enabled": True,
        "comment": "note",
    }


async def test_rfid_delete_uses_query_param(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.delete(f"{BASE}/rfid", json=ack())
    await _client(hass).async_delete_rfid_tag("0A1B2C3D")
    assert aioclient_mock.mock_calls[-1][1].query["id"] == "0A1B2C3D"


async def test_rfid_learn_defaults_send_no_params(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With no arguments the firmware defaults apply, so send no params block."""
    aioclient_mock.post(f"{BASE}/rfid/extras", json=ack())
    client = _client(hass)

    await client.async_rfid_learn()
    assert aioclient_mock.mock_calls[-1][2] == {"command": "rfid_learn"}

    await client.async_rfid_learn(timeout_sec=60, count_max=2)
    assert aioclient_mock.mock_calls[-1][2] == {
        "command": "rfid_learn",
        "params": {"timeout_sec": 60, "count_max": 2},
    }

    await client.async_rfid_learn_cancel()
    assert aioclient_mock.mock_calls[-1][2] == {"command": "rfid_learn_cancel"}


async def test_null_error_code_with_internal_status(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An explicit null error_code must not let an internal condition through."""
    aioclient_mock.get(
        f"{BASE}/status", json={"error_code": None, "status": "internal error"}
    )
    with pytest.raises(VoltieChargerConnectionError, match="internal error"):
        await _client(hass).async_get_status()
