"""Tests for the device-targeted services."""
from __future__ import annotations

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.voltie_charger.const import DOMAIN

from .conftest import BASE, ack, legacy_config_payload, setup_integration

CHARGER_IDENTIFIER = "000000009d104335"


def _last(aioclient_mock, method: str, path: str):
    """Return the last call to method+path.

    RFID mutations trigger a coordinator refresh afterwards, so the mutation is
    not the final entry in mock_calls.
    """
    matches = [
        c for c in aioclient_mock.mock_calls if c[0] == method and c[1].path == path
    ]
    assert matches, f"no {method} {path} call was made"
    return matches[-1]


@pytest.fixture
async def device_id(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, device_registry
) -> str:
    """Set up a v5 charger and return its device_id."""
    mock_charger()
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, CHARGER_IDENTIFIER)}
    )
    return device.id


async def test_all_services_registered(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    for name in (
        "display_text",
        "set_rear_led",
        "start_charging",
        "add_rfid_tag",
        "modify_rfid_tag",
        "delete_rfid_tag",
        "list_rfid_tags",
        "start_rfid_learn",
    ):
        assert hass.services.has_service(DOMAIN, name), name


async def test_display_text(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "display_text",
        {
            "device_id": device_id,
            "message": "Charging done",
            "repeat_count": 3,
            "clear_first": True,
        },
        blocking=True,
    )
    assert aioclient_mock.mock_calls[-1][2] == {
        "command": "display_scroll_text",
        "params": {
            "message": "Charging done",
            "repeat_count": 3,
            "clear_first": True,
        },
    }


async def test_display_text_omits_unset_optionals(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unset optionals must not be sent, so firmware defaults apply."""
    await hass.services.async_call(
        DOMAIN,
        "display_text",
        {"device_id": device_id, "message": "hi"},
        blocking=True,
    )
    assert aioclient_mock.mock_calls[-1][2]["params"] == {"message": "hi"}


@pytest.mark.parametrize("message", ["", "x" * 101])
async def test_display_text_rejects_bad_message_length(
    hass: HomeAssistant, device_id: str, message: str
) -> None:
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "display_text",
            {"device_id": device_id, "message": message},
            blocking=True,
        )


async def test_display_text_rejects_out_of_range_repeat(
    hass: HomeAssistant, device_id: str
) -> None:
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "display_text",
            {"device_id": device_id, "message": "hi", "repeat_count": 6},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("supplied", "sent"),
    [("#FF8800", "#FF8800"), ("FF8800", "#FF8800"), ("ff8800", "#FF8800")],
)
async def test_set_rear_led_normalises_colour(
    hass: HomeAssistant,
    device_id: str,
    aioclient_mock: AiohttpClientMocker,
    supplied: str,
    sent: str,
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "set_rear_led",
        {"device_id": device_id, "brightness": 0.6, "color_rgb": supplied},
        blocking=True,
    )
    assert aioclient_mock.mock_calls[-1][2] == {
        "command": "rear_led_set",
        "params": {"brightness": 0.6, "color_rgb": sent},
    }


@pytest.mark.parametrize("colour", ["red", "#FFF", "#GGHHII", "#FF88000"])
async def test_set_rear_led_rejects_bad_colour(
    hass: HomeAssistant, device_id: str, colour: str
) -> None:
    with pytest.raises(ServiceValidationError, match="hex RGB"):
        await hass.services.async_call(
            DOMAIN,
            "set_rear_led",
            {"device_id": device_id, "brightness": 0.5, "color_rgb": colour},
            blocking=True,
        )


async def test_set_rear_led_rejects_out_of_range_brightness(
    hass: HomeAssistant, device_id: str
) -> None:
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_rear_led",
            {"device_id": device_id, "brightness": 1.5, "color_rgb": "#FFFFFF"},
            blocking=True,
        )


async def test_start_charging_with_id_tag(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """Hyphens are legal in id_tag since API 4.3."""
    await hass.services.async_call(
        DOMAIN,
        "start_charging",
        {"device_id": device_id, "id_tag": "1A2B-3C4D", "name": "Jane Doe"},
        blocking=True,
    )
    start = [c for c in aioclient_mock.mock_calls if "start" in str(c[1])][-1]
    assert start[1].query["id_tag"] == "1A2B-3C4D"
    assert start[1].query["name"] == "Jane Doe"


async def test_start_charging_defaults_name(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without a name, sessions look the same as ones from the switch."""
    await hass.services.async_call(
        DOMAIN, "start_charging", {"device_id": device_id}, blocking=True
    )
    start = [c for c in aioclient_mock.mock_calls if "start" in str(c[1])][-1]
    assert start[1].query["name"] == "homeassistant"


async def test_start_charging_rejects_short_id_tag(
    hass: HomeAssistant, device_id: str
) -> None:
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "start_charging",
            {"device_id": device_id, "id_tag": "TOOSHRT"},
            blocking=True,
        )


async def test_add_rfid_tag(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_rfid_tag",
        {
            "device_id": device_id,
            "id": "0A1B2C3D",
            "name": "John Doe",
            "enabled": True,
            "comment": "note",
        },
        blocking=True,
    )
    assert _last(aioclient_mock, "POST", "/rfid")[2] == {
        "id": "0A1B2C3D",
        "name": "John Doe",
        "enabled": True,
        "comment": "note",
    }


@pytest.mark.parametrize(
    "tag_id",
    [
        "SHORT",           # under the 8-char minimum
        "A" * 21,          # over the 20-char maximum
        "bad id!",         # punctuation
        "CLAUDETEST01",    # right length, but not hexadecimal
        "0A1B2C3G",        # G is not a hex digit
    ],
)
async def test_add_rfid_tag_rejects_bad_id(
    hass: HomeAssistant, device_id: str, tag_id: str
) -> None:
    """The firmware only accepts hex ids, despite what spec 4.11.1 documents."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "add_rfid_tag",
            {"device_id": device_id, "id": tag_id},
            blocking=True,
        )


async def test_modify_rfid_tag_requires_a_changed_field(
    hass: HomeAssistant, device_id: str
) -> None:
    """An id-only PUT would change nothing (spec 4.11.4)."""
    with pytest.raises(ServiceValidationError, match="at least one"):
        await hass.services.async_call(
            DOMAIN,
            "modify_rfid_tag",
            {"device_id": device_id, "id": "0A1B2C3D"},
            blocking=True,
        )


async def test_modify_rfid_tag_sends_only_given_fields(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "modify_rfid_tag",
        {"device_id": device_id, "id": "0A1B2C3D", "enabled": False},
        blocking=True,
    )
    assert _last(aioclient_mock, "PUT", "/rfid")[2] == {
        "id": "0A1B2C3D",
        "enabled": False,
    }


async def test_delete_rfid_tag(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "delete_rfid_tag",
        {"device_id": device_id, "id": "0A1B2C3D"},
        blocking=True,
    )
    assert _last(aioclient_mock, "DELETE", "/rfid")[1].query["id"] == "0A1B2C3D"


async def test_list_rfid_tags_returns_response(
    hass: HomeAssistant, device_id: str
) -> None:
    response = await hass.services.async_call(
        DOMAIN,
        "list_rfid_tags",
        {"device_id": device_id},
        blocking=True,
        return_response=True,
    )
    assert response["count"] == 2
    assert response["list_hash"] == "A3F21B8C"
    assert [t["id"] for t in response["tags"]] == ["0A1B2C3D", "1122334455"]


async def test_list_rfid_tags_paging(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "list_rfid_tags",
        {"device_id": device_id, "first_item": 10, "max_count": 5},
        blocking=True,
        return_response=True,
    )
    query = aioclient_mock.mock_calls[-1][1].query
    assert query["first_item"] == "10"
    assert query["max_count"] == "5"


async def test_rfid_services_rejected_on_pre_v5_firmware(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, device_registry
) -> None:
    """A clear message beats letting the request 404."""
    mock_charger(rfid_supported=False, apiver=4, config=legacy_config_payload())
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, CHARGER_IDENTIFIER)}
    )

    with pytest.raises(ServiceValidationError, match="API v5"):
        await hass.services.async_call(
            DOMAIN,
            "add_rfid_tag",
            {"device_id": device.id, "id": "0A1B2C3D"},
            blocking=True,
        )


async def test_service_on_unknown_device(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    with pytest.raises(ServiceValidationError, match="No device"):
        await hass.services.async_call(
            DOMAIN,
            "display_text",
            {"device_id": "does-not-exist", "message": "hi"},
            blocking=True,
        )


async def test_service_charger_error_surfaces(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """error_code 5 from the charger becomes a HomeAssistantError."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/rfid", json=ack(error_code=5))

    with pytest.raises(HomeAssistantError, match="rejected"):
        await hass.services.async_call(
            DOMAIN,
            "add_rfid_tag",
            {"device_id": device_id, "id": "0A1B2C3D"},
            blocking=True,
        )


async def test_services_survive_entry_reload(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """Registration happens in async_setup, so a reload must not drop them."""
    mock_charger()
    await setup_integration(hass, config_entry)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "display_text")


async def test_rfid_mutations_refresh_the_status_sensors(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """Otherwise list_count/list_hash lag by up to a whole scan interval."""
    before = len(
        [c for c in aioclient_mock.mock_calls if c[1].path == "/rfid/status"]
    )
    await hass.services.async_call(
        DOMAIN,
        "add_rfid_tag",
        {"device_id": device_id, "id": "0A1B2C3D"},
        blocking=True,
    )
    await hass.async_block_till_done()
    after = len([c for c in aioclient_mock.mock_calls if c[1].path == "/rfid/status"])
    assert after > before


async def test_start_rfid_learn_with_params(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """The button uses firmware defaults; this service carries the parameters."""
    await hass.services.async_call(
        DOMAIN,
        "start_rfid_learn",
        {"device_id": device_id, "timeout_sec": 60, "count_max": 2},
        blocking=True,
    )
    assert _last(aioclient_mock, "POST", "/rfid/extras")[2] == {
        "command": "rfid_learn",
        "params": {"timeout_sec": 60, "count_max": 2},
    }


async def test_start_rfid_learn_defaults(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    await hass.services.async_call(
        DOMAIN, "start_rfid_learn", {"device_id": device_id}, blocking=True
    )
    assert _last(aioclient_mock, "POST", "/rfid/extras")[2] == {
        "command": "rfid_learn"
    }


async def test_area_target_is_rejected_not_silently_dropped(
    hass: HomeAssistant, device_id: str
) -> None:
    """Dropping the area part would skip chargers the user selected."""
    with pytest.raises(Exception, match="areas, floors, labels"):
        await hass.services.async_call(
            DOMAIN,
            "display_text",
            {"device_id": device_id, "area_id": ["garage"], "message": "hi"},
            blocking=True,
        )


async def test_not_master_error_does_not_blame_firmware(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """error_code 23 is a cluster topology problem, not old firmware."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/rfid", json=ack(error_code=23))

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "add_rfid_tag",
            {"device_id": device_id, "id": "0A1B2C3D"},
            blocking=True,
        )
    assert "master unit" in str(err.value)
    assert "update" not in str(err.value).lower()


async def test_unsupported_add_is_not_reported_as_a_duplicate(
    hass: HomeAssistant, device_id: str, aioclient_mock: AiohttpClientMocker
) -> None:
    """VoltieChargerUnsupportedError subclasses the rejected error.

    Matched in the wrong order it would tell the user a tag already exists when
    the real problem is that the firmware has no /rfid endpoint.
    """
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/rfid", json=ack(error_code=24))

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "add_rfid_tag",
            {"device_id": device_id, "id": "0A1B2C3D"},
            blocking=True,
        )
    assert "already stored" not in str(err.value)
    assert "firmware" in str(err.value).lower()
