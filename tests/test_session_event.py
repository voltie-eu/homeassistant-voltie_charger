"""The session_finished event: detection, final values and no duplicates."""
from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.voltie_charger.const import DEFAULT_SCAN_INTERVAL

from .conftest import BASE, ack, cdr_payload, setup_integration, status_payload

EID = "event.voltie_charger_4335_charging_session"
START = 1708335000
END = 1708338400


def _charging(**cdr_overrides) -> dict:
    return status_payload(
        evse_state=3,
        is_car_connected=True,
        is_charging=True,
        cdr=cdr_payload(**cdr_overrides),
    )


def _unplugged(**overrides) -> dict:
    return status_payload(evse_state=1, cdr=None, last_cdr=446, **overrides)


def _closed(**overrides) -> dict:
    """The record GET /cdr returns once the session has closed."""
    return cdr_payload(chg_energy=5.9, chg_time=3300, s_end=END, **overrides)


def _iso(timestamp: int) -> str:
    return dt_util.utc_from_timestamp(timestamp).isoformat()


async def _poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    mock_charger,
    status: dict,
    *,
    cdr: dict | None = None,
    cdr_status: int | None = None,
) -> None:
    """Make the charger answer differently from the next poll on, and run it."""
    aioclient_mock.clear_requests()
    if cdr_status is not None:
        aioclient_mock.get(f"{BASE}/cdr", status=cdr_status)
    elif cdr is not None:
        aioclient_mock.get(
            f"{BASE}/cdr?cdr_id={cdr['cdr_id']}", json=ack(cdr=cdr)
        )
    mock_charger(status=status)
    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_unplugging_reports_the_closed_record(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The event carries the final figures, not the last poll's (VLT-2891)."""
    mock_charger(status=_charging())
    await setup_integration(hass, config_entry)
    assert hass.states.get(EID).state == STATE_UNKNOWN

    await _poll(
        hass, freezer, aioclient_mock, mock_charger, _unplugged(), cdr=_closed()
    )

    state = hass.states.get(EID)
    assert state.attributes["event_type"] == "session_finished"
    assert state.attributes["energy_kwh"] == 5.9
    assert state.attributes["charge_time_s"] == 3300
    assert state.attributes["idle_time_s"] == 240
    assert state.attributes["avg_power_kw"] == 6.75
    assert state.attributes["max_power_kw"] == 7.2
    assert state.attributes["idtag_name"] == "John Doe"
    assert state.attributes["cdr_id"] == 446
    assert state.attributes["session_start"] == _iso(START)
    assert state.attributes["session_end"] == _iso(END)
    assert state.attributes["closed_after_restart"] is False
    fired_at = state.state

    # Staying unplugged is not a second session.
    await _poll(hass, freezer, aioclient_mock, mock_charger, _unplugged())
    assert hass.states.get(EID).state == fired_at


async def test_renumbered_session_is_not_a_new_one(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The firmware renumbers an active record when it resyncs its IDs.

    Reporting a changed cdr_id as the end of a session would fire for a
    session that is still charging.
    """
    mock_charger(status=_charging(cdr_id=5))
    await setup_integration(hass, config_entry)

    await _poll(hass, freezer, aioclient_mock, mock_charger, _charging(cdr_id=446))
    assert hass.states.get(EID).state == STATE_UNKNOWN

    # When it does end, the record is found under its new number.
    await _poll(
        hass, freezer, aioclient_mock, mock_charger, _unplugged(), cdr=_closed()
    )
    assert hass.states.get(EID).attributes["energy_kwh"] == 5.9


async def test_replugging_between_polls_ends_the_first_session(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_charger(status=_charging())
    await setup_integration(hass, config_entry)

    second = status_payload(
        evse_state=2,
        is_car_connected=True,
        last_cdr=446,
        cdr=cdr_payload(cdr_id=447, s_start=START + 5000, chg_energy=0),
    )
    await _poll(hass, freezer, aioclient_mock, mock_charger, second, cdr=_closed())

    state = hass.states.get(EID)
    assert state.attributes["session_start"] == _iso(START)
    assert state.attributes["energy_kwh"] == 5.9


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"cdr_status": 500}, id="record unavailable"),
        # A stale record under the same number belongs to another session.
        pytest.param({"cdr": _closed(s_start=START - 86400)}, id="other session"),
    ],
)
async def test_falls_back_to_the_last_poll(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    answer: dict,
) -> None:
    """Without the closed record the event still fires, with what was seen."""
    mock_charger(status=_charging(chg_energy=5.852))
    await setup_integration(hass, config_entry)

    await _poll(hass, freezer, aioclient_mock, mock_charger, _unplugged(), **answer)

    state = hass.states.get(EID)
    assert state.attributes["session_start"] == _iso(START)
    assert state.attributes["energy_kwh"] == 5.852
    assert state.attributes["session_end"] is None


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(
            {k: v for k, v in _charging().items() if k != "cdr"}, id="no cdr key"
        ),
        pytest.param(_charging() | {"cdr": "garbage"}, id="malformed cdr"),
        pytest.param(_charging() | {"cdr": {"cdr_id": 446}}, id="no start time"),
    ],
)
async def test_incomplete_reading_does_not_end_the_session(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    status: dict,
) -> None:
    mock_charger(status=_charging())
    await setup_integration(hass, config_entry)

    await _poll(hass, freezer, aioclient_mock, mock_charger, status)
    assert hass.states.get(EID).state == STATE_UNKNOWN

    # The session is still tracked, so its real end is reported.
    await _poll(
        hass, freezer, aioclient_mock, mock_charger, _unplugged(), cdr=_closed()
    )
    assert hass.states.get(EID).attributes["energy_kwh"] == 5.9


async def test_session_ending_while_home_assistant_is_down(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_storage,
) -> None:
    """A session seen before a restart is reported once it is back."""
    mock_charger(status=_charging())
    await setup_integration(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage[f"voltie_charger.{config_entry.entry_id}.session"]
    assert stored["data"]["session"]["s_start"] == START

    # The car is unplugged meanwhile.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/cdr?cdr_id=446", json=ack(cdr=_closed()))
    mock_charger(status=_unplugged())
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(EID)
    assert state.attributes["session_start"] == _iso(START)
    assert state.attributes["session_end"] == _iso(END)
    assert state.attributes["energy_kwh"] == 5.9


async def test_no_duplicate_after_a_restart(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    hass_storage,
) -> None:
    """Neither the store nor the restored event may fire a session again.

    The second restart simulates a crash that lost the store's last write: the
    charger still reports the session as closed, and only the event entity's
    restored state prevents a second report.
    """
    mock_charger(status=_charging())
    await setup_integration(hass, config_entry)
    await _poll(
        hass, freezer, aioclient_mock, mock_charger, _unplugged(), cdr=_closed()
    )
    fired_at = hass.states.get(EID).state

    for lose_store_write in (False, True):
        # A repeat would then carry a later timestamp than the original.
        freezer.tick(timedelta(minutes=5))
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
        if lose_store_write:
            hass_storage[f"voltie_charger.{config_entry.entry_id}.session"][
                "data"
            ]["session"] = {
                "charger_id": "000000009d104335",
                "s_start": START,
                "cdr_id": 446,
            }
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(EID).state == fired_at, lose_store_write


async def test_a_different_charger_does_not_end_the_session(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A replacement charger at the same address has none of its sessions."""
    mock_charger(status=_charging())
    await setup_integration(hass, config_entry)

    await _poll(
        hass,
        freezer,
        aioclient_mock,
        mock_charger,
        _unplugged(charger_id="00000000bdadfbe1"),
        cdr=_closed(),
    )
    assert hass.states.get(EID).state == STATE_UNKNOWN
