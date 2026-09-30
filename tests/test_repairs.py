"""Repair issues and the reload that follows a firmware update (VLT-2891)."""
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

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.voltie_charger.client import VoltieChargerConnectionError
from custom_components.voltie_charger.const import (
    AUTH_RECHECK_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import BASE, legacy_config_payload, setup_integration, status_payload

PREFIX = "voltie_charger_4335"
ANONYMOUS_PROBE = (
    "custom_components.voltie_charger.client.VoltieChargerClient"
    ".async_accepts_anonymous"
)


def _issue(issue_registry: ir.IssueRegistry, kind: str, entry: MockConfigEntry):
    return issue_registry.async_get_issue(DOMAIN, f"{kind}_{entry.entry_id}")


def _with_credentials(config_entry: MockConfigEntry) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=config_entry.unique_id,
        version=2,
        data={**config_entry.data, CONF_USERNAME: "admin", CONF_PASSWORD: "secret"},
    )


# ---- outdated firmware ----


@pytest.mark.parametrize(
    "apiver",
    [
        pytest.param(4, id="API v4"),
        pytest.param(None, id="no /apiver at all"),
    ],
)
async def test_old_firmware_raises_an_issue(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    apiver: int | None,
) -> None:
    """Old firmware silently lacks the RFID entities; say why instead."""
    mock_charger(apiver=apiver, rfid_supported=False, config=legacy_config_payload())
    await setup_integration(hass, config_entry)

    issue = _issue(issue_registry, "outdated_firmware", config_entry)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"name": "Voltie Charger 4335"}


async def test_current_firmware_has_no_issue(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    mock_charger(apiver=5)
    await setup_integration(hass, config_entry)
    assert _issue(issue_registry, "outdated_firmware", config_entry) is None


async def test_apiver_timeout_is_no_verdict(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Only a definitive answer may raise or clear the issue."""
    aioclient_mock.get(f"{BASE}/apiver", exc=TimeoutError())
    mock_charger()
    await setup_integration(hass, config_entry)
    assert _issue(issue_registry, "outdated_firmware", config_entry) is None


async def test_firmware_update_reloads_and_clears_the_issue(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """New firmware brings its entities and clears its issue by itself.

    Features are probed at setup only, so without the reload the RFID entities
    would stay missing and the issue open until Home Assistant restarted.
    """
    mock_charger(apiver=4, rfid_supported=False, config=legacy_config_payload())
    await setup_integration(hass, config_entry)
    assert _issue(issue_registry, "outdated_firmware", config_entry) is not None
    assert hass.states.get(f"sensor.{PREFIX}_rfid_tags_stored") is None

    # The charger updates itself overnight.
    aioclient_mock.clear_requests()
    mock_charger(status=status_payload(sw_ver=1003042), apiver=5)
    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _issue(issue_registry, "outdated_firmware", config_entry) is None
    assert hass.states.get(f"sensor.{PREFIX}_rfid_tags_stored").state == "5"
    assert hass.states.get(f"sensor.{PREFIX}_api_version").state == "5"


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
            freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
    reload.assert_not_called()


# ---- HTTP API without authentication ----


async def test_api_without_credentials_raises_an_issue(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    issue = _issue(issue_registry, "unauthenticated_api", config_entry)
    assert issue is not None
    assert issue.translation_placeholders == {"name": "Voltie Charger 4335"}


@pytest.mark.parametrize(
    ("accepts_anonymous", "has_issue"), [(True, True), (False, False)]
)
async def test_credentials_alone_do_not_prove_protection(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    accepts_anonymous: bool,
    has_issue: bool,
) -> None:
    """A charger with auth switched off accepts any credentials it is sent."""
    entry = _with_credentials(config_entry)
    mock_charger()
    with patch(ANONYMOUS_PROBE, return_value=accepts_anonymous):
        await setup_integration(hass, entry)
    assert (_issue(issue_registry, "unauthenticated_api", entry) is not None) is (
        has_issue
    )


async def test_probe_survives_one_busy_answer(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A single 503 at startup must not hide an open API until the recheck.

    Seen live: a charger answering 503 now and then left the issue unraised
    after a restart, because the probe was the only request without a retry.
    """
    mock_charger()
    busy = VoltieChargerConnectionError("HTTP 503 from status: Service Unavailable")
    with patch(ANONYMOUS_PROBE, side_effect=[busy, True]):
        await setup_integration(hass, config_entry)
    assert _issue(issue_registry, "unauthenticated_api", config_entry) is not None


async def test_enabling_auth_clears_the_issue_later(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Turning auth on with the credentials HA already has changes nothing HA
    would otherwise notice, so the periodic re-check has to clear it."""
    entry = _with_credentials(config_entry)
    mock_charger()
    with patch(ANONYMOUS_PROBE, return_value=True):
        await setup_integration(hass, entry)
    assert _issue(issue_registry, "unauthenticated_api", entry) is not None

    with patch(ANONYMOUS_PROBE, return_value=False):
        freezer.tick(AUTH_RECHECK_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert _issue(issue_registry, "unauthenticated_api", entry) is None


async def test_enabling_auth_clears_the_issue_without_credentials(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The charger now rejects every anonymous request, this entry's too."""
    mock_charger()
    await setup_integration(hass, config_entry)
    assert _issue(issue_registry, "unauthenticated_api", config_entry) is not None

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", status=401)
    freezer.tick(AUTH_RECHECK_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _issue(issue_registry, "unauthenticated_api", config_entry) is None


async def test_ignored_issue_stays_ignored(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Running without a password on purpose must not nag on every restart."""
    mock_charger()
    await setup_integration(hass, config_entry)
    issue_id = f"unauthenticated_api_{config_entry.entry_id}"
    ir.async_ignore_issue(hass, DOMAIN, issue_id, True)

    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue_id).dismissed_version


async def test_removing_the_entry_removes_its_leftovers(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    hass_storage,
) -> None:
    mock_charger(apiver=4, rfid_supported=False, config=legacy_config_payload())
    await setup_integration(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    store_key = f"voltie_charger.{config_entry.entry_id}.session"
    assert store_key in hass_storage

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(issue_registry, "outdated_firmware", config_entry) is None
    assert _issue(issue_registry, "unauthenticated_api", config_entry) is None
    assert store_key not in hass_storage
