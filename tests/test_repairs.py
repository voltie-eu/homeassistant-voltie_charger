"""No repair issues since v0.5.0, and the reload after a firmware update.

v0.4.0 raised an issue for firmware older than HTTP API v5 and one for an
HTTP API without a password. Neither was something to repair from Home
Assistant, and the built-in integration has neither. Deleting the ones left
behind is tested in test_migration.py.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.voltie_charger.const import DOMAIN, SCAN_INTERVAL

from .conftest import legacy_config_payload, setup_integration, status_payload

PREFIX = "voltie_charger_4335"


@pytest.mark.parametrize(
    "apiver",
    [
        pytest.param(4, id="API v4"),
        pytest.param(None, id="no /apiver at all"),
    ],
)
async def test_no_issue_for_old_firmware_or_an_open_api(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    apiver: int | None,
) -> None:
    """The fixture charger has no password and, here, old firmware."""
    mock_charger(apiver=apiver, rfid_supported=False, config=legacy_config_payload())
    await setup_integration(hass, config_entry)
    assert config_entry.state.name == "LOADED"
    assert not [
        issue_id
        for (domain, issue_id) in issue_registry.issues
        if domain == DOMAIN
    ]


async def test_firmware_update_reloads_and_adds_its_entities(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """New firmware brings its entities by itself.

    Features are probed at setup only, so without the reload the RFID entities
    would stay missing until Home Assistant restarted.
    """
    mock_charger(apiver=4, rfid_supported=False, config=legacy_config_payload())
    await setup_integration(hass, config_entry)
    assert hass.states.get(f"sensor.{PREFIX}_rfid_tags_stored") is None

    # The charger updates itself overnight.
    aioclient_mock.clear_requests()
    mock_charger(status=status_payload(sw_ver=1003042), apiver=5)
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(f"sensor.{PREFIX}_rfid_tags_stored").state == "5"
    assert config_entry.runtime_data.api_version == 5


async def test_unchanged_software_does_not_reload(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        for _ in range(3):
            freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
    reload.assert_not_called()


async def test_removing_the_entry_removes_its_leftovers(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    hass_storage,
) -> None:
    """The session store, and an issue of an entry not set up since v0.4.0."""
    mock_charger()
    await setup_integration(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    store_key = f"voltie_charger.{config_entry.entry_id}.session"
    assert store_key in hass_storage
    issue_id = f"unauthenticated_api_{config_entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="unauthenticated_api",
    )

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
    assert store_key not in hass_storage
