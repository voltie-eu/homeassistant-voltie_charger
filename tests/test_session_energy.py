"""Keep session energy usable by Recorder between charging sessions."""
from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.voltie_charger.const import DATA_STATUS

from .conftest import setup_integration, status_payload

ENTITY_ID = "sensor.voltie_charger_4335_session_energy"


async def test_idle_session_energy_is_zero(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """An explicit empty session on a disconnected charger stays numeric."""
    mock_charger(status=status_payload(cdr=None, evse_state=1))
    await setup_integration(hass, config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "0"
    assert state.attributes["state_class"] == "total_increasing"
    assert state.attributes["unit_of_measurement"] == "kWh"


@pytest.mark.parametrize(
    "status",
    [
        {"evse_state": 1},  # Missing CDR is not an explicit empty session.
        {"cdr": None},
        {"cdr": None, "evse_state": 0},
        {"cdr": None, "evse_state": 2},
        {"cdr": None, "evse_state": 3},
        {"cdr": {}, "evse_state": 1},
        {"cdr": "invalid", "evse_state": 1},
    ],
)
async def test_incomplete_session_is_not_fabricated_zero(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry,
    status: dict[str, Any],
) -> None:
    """Unknown/malformed responses must not introduce a false counter reset."""
    payload = status_payload()
    payload.pop("cdr")
    payload.pop("evse_state")
    payload.update(status)
    mock_charger(status=payload)
    await setup_integration(hass, config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN


@pytest.mark.parametrize("value", [None, True, "5", -1, float("nan"), float("inf"), {}])
async def test_invalid_session_energy_is_unknown(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, value: Any,
) -> None:
    """Invalid energy must not raise or produce a misleading numeric state."""
    mock_charger(status=status_payload(cdr={"chg_energy": value}, evse_state=3))
    await setup_integration(hass, config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN


async def test_session_idle_and_new_session_transitions(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """Keep the measured value until the API explicitly clears the session."""
    mock_charger(status=status_payload(cdr={"chg_energy": 41.881}, evse_state=3))
    await setup_integration(hass, config_entry)
    coordinator = config_entry.runtime_data
    assert hass.states.get(ENTITY_ID).state == "41.881"

    for cdr, evse_state, expected in (
        ({"chg_energy": 41.881}, 1, "41.881"),
        (None, 1, "0"),
        (None, 1, "0"),
        ({"chg_energy": 0.002}, 3, "0.002"),
        ({"chg_energy": 5.852}, 3, "5.852"),
    ):
        coordinator.async_set_updated_data({
            **coordinator.data,
            DATA_STATUS: status_payload(cdr=cdr, evse_state=evse_state),
        })
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY_ID).state == expected


async def test_connection_failure_remains_unavailable(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """A cached idle response must not hide a failed poll."""
    mock_charger()
    await setup_integration(hass, config_entry)
    config_entry.runtime_data.async_set_update_error(UpdateFailed("connection lost"))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
