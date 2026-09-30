"""Session energy through Home Assistant's real recorder across a long break.

PR #1 reported negative consumption on the Energy dashboard after a long pause
between sessions. Its author could not reproduce that on a clean database, and
his tests stopped short of the recorder. This runs a session, an 11-day break
with statistics compiled daily as Home Assistant does, a purge with the default
10-day retention and the next session, with and without the fix.
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_purge_done,
    async_wait_recording_done,
    do_adhoc_statistics,
    statistics_during_period,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant

from custom_components.voltie_charger import sensor

from .conftest import cdr_payload, setup_integration, status_payload

EID = "sensor.voltie_charger_4335_session_energy"


@pytest.fixture
async def mock_recorder_before_hass(async_test_recorder) -> None:
    """Prepare the recorder's database before hass starts, as it requires."""
FIRST = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
SECOND = FIRST + timedelta(days=11)


def _charging(start: datetime, energy: float) -> dict:
    return status_payload(
        evse_state=3,
        is_car_connected=True,
        is_charging=True,
        cdr=cdr_payload(s_start=int(start.timestamp()), chg_energy=energy),
    )


IDLE = status_payload(evse_state=1, cdr=None)


def _without_the_fix() -> tuple:
    """SENSORS with session energy read the way v0.3.0 did."""
    return tuple(
        dataclasses.replace(
            description, value_fn=lambda d: sensor._cdr(d).get("chg_energy")
        )
        if description.key == "session_energy"
        else description
        for description in sensor.SENSORS
    )


@pytest.mark.parametrize("fixed", [True, False], ids=["with fix", "v0.3.0"])
async def test_long_break_keeps_energy_statistics_continuous(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
    fixed: bool,
) -> None:
    if not fixed:
        monkeypatch.setattr(sensor, "SENSORS", _without_the_fix())

    async def report(when: datetime, status: dict) -> None:
        freezer.move_to(when)
        aioclient_mock.clear_requests()
        mock_charger(status=status)
        await config_entry.runtime_data.async_refresh()
        await async_wait_recording_done(hass)

    async def compile_hour(hour: datetime) -> None:
        # Every 5-minute period; the one starting at :55 also compiles the hour.
        for minute in range(0, 60, 5):
            freezer.move_to(hour + timedelta(minutes=minute + 5))
            do_adhoc_statistics(hass, start=hour + timedelta(minutes=minute))
            await async_wait_recording_done(hass)

    # A 5 kWh session, then the car is unplugged.
    freezer.move_to(FIRST)
    mock_charger(status=_charging(FIRST, 0))
    await setup_integration(hass, config_entry)
    await report(FIRST + timedelta(minutes=20), _charging(FIRST, 2.5))
    await report(FIRST + timedelta(minutes=40), _charging(FIRST, 5.0))
    await report(FIRST + timedelta(minutes=50), IDLE)
    assert hass.states.get(EID).state == ("0" if fixed else "unknown")
    await compile_hour(FIRST)

    # Eleven idle days, with statistics compiled each day as they would be.
    for day in range(1, 11):
        await compile_hour(FIRST + timedelta(days=day, hours=1))

    # The nightly purge, at Home Assistant's default 10-day retention.
    freezer.move_to(SECOND - timedelta(minutes=30))
    await hass.services.async_call("recorder", "purge", {"keep_days": 10})
    await async_wait_purge_done(hass)

    # The next session charges 3 kWh.
    await report(SECOND, _charging(SECOND, 0))
    await report(SECOND + timedelta(minutes=30), _charging(SECOND, 3.0))
    await compile_hour(SECOND)

    rows = (
        await hass.async_add_executor_job(
            statistics_during_period,
            hass,
            FIRST - timedelta(hours=1),
            SECOND + timedelta(hours=1),
            {EID},
            "hour",
            None,
            {"sum"},
        )
    )[EID]
    sums = [row["sum"] for row in rows]
    changes = [after - before for before, after in pairwise(sums)]

    if fixed:
        # Every hour's consumption is non-negative and the total carries on.
        assert min(changes) >= 0, changes
        assert sums[-1] == pytest.approx(8.0)
    else:
        # The report, reproduced on a clean database: once the purge removed
        # the last short-term row, the sum restarted and the dashboard shows
        # the second session as a drop of 2 kWh.
        assert min(changes) == pytest.approx(-2.0), changes
