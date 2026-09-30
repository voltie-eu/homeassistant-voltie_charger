"""Setup and coordinator behaviour, including the soft-fail latches."""
from __future__ import annotations

from datetime import timedelta
import json

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.voltie_charger.const import (
    CONFIG_REPROBE_EVERY,
    DATA_CONFIG,
    DATA_RFID_STATUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import (
    charger_device,
    BASE,
    CHARGER_ID,
    cdr_payload,
    config_payload,
    power_payload,
    setup_integration,
    status_payload,
)

PREFIX = "voltie_charger_4335"


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Move past one coordinator tick."""
    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_uses_configured_port(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A non-default port must be used for every request (VLT-2120 M2)."""
    base = "http://192.168.1.234:9000"
    aioclient_mock.get(f"{base}/status", json=status_payload())
    aioclient_mock.get(f"{base}/power", json=power_payload())
    aioclient_mock.get(f"{base}/config", json=config_payload())
    aioclient_mock.get(f"{base}/apiver", json={"api_files_version": 5})
    aioclient_mock.get(f"{base}/rfid/status", status=404)

    entry = MockConfigEntry(
        domain=config_entry.domain,
        unique_id=config_entry.unique_id,
        data={**config_entry.data, "port": 9000},
    )
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert all(call[1].port == 9000 for call in aioclient_mock.mock_calls)


async def test_setup_retries_when_unreachable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    aioclient_mock.get(f"{BASE}/status", exc=TimeoutError())
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_starts_reauth_on_401(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    aioclient_mock.get(f"{BASE}/status", status=401)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_setup_retries_without_charger_id(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Without a charger_id there is no stable device identity yet."""
    status = status_payload()
    status.pop("charger_id")
    aioclient_mock.get(f"{BASE}/status", json=status)
    aioclient_mock.get(f"{BASE}/power", json=power_payload())
    aioclient_mock.get(f"{BASE}/config", json=config_payload())
    aioclient_mock.get(f"{BASE}/rfid/status", status=404)
    aioclient_mock.get(f"{BASE}/apiver", json={"api_files_version": 5})

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_power_failure_carries_forward(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A dropped /power keeps the last readings rather than blanking them."""
    mock_charger()
    await setup_integration(hass, config_entry)
    assert float(hass.states.get(f"sensor.{PREFIX}_voltage_l1").state) == 231.461

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/power", exc=TimeoutError())
    mock_charger()
    await _advance(hass, freezer)

    # Still the carried-forward value, and the entity is not unavailable.
    state = hass.states.get(f"sensor.{PREFIX}_voltage_l1")
    assert state.state != STATE_UNAVAILABLE
    assert float(state.state) == 231.461


async def test_status_failure_marks_unavailable(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """/status is the one endpoint whose failure must fail the update."""
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", exc=TimeoutError())
    await _advance(hass, freezer)
    assert hass.states.get(f"sensor.{PREFIX}_charge_power").state == STATE_UNAVAILABLE


async def test_config_soft_fail_latch_stops_polling(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A /config the firmware reports missing is only re-probed periodically."""
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/config", status=404)
    mock_charger()
    await _advance(hass, freezer)

    def config_calls() -> int:
        return len(
            [
                c
                for c in aioclient_mock.mock_calls
                if c[0] == "GET" and c[1].path == "/config"
            ]
        )

    after_failure = config_calls()
    # The next few ticks must not touch /config at all.
    for _ in range(3):
        await _advance(hass, freezer)
    assert config_calls() == after_failure

    # ...but it is retried once the re-probe window elapses.
    for _ in range(CONFIG_REPROBE_EVERY + 1):
        await _advance(hass, freezer)
    assert config_calls() > after_failure


async def test_config_values_carried_forward_on_failure(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/config", exc=TimeoutError())
    mock_charger()
    await _advance(hass, freezer)

    coordinator = config_entry.runtime_data
    assert coordinator.data[DATA_CONFIG]["conf_current_limit"] == 16


async def test_config_timeout_does_not_freeze_values(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A single /config timeout must not stop /config polling (VLT-2890).

    Latching it stopped polling for the whole re-probe window, so a limit
    changed in the app stayed invisible for ten minutes while the entity kept
    presenting the old value as current. Weak-WiFi chargers hit this routinely.
    """
    eid = f"number.{PREFIX}_maximum_charging_current"
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/config", exc=TimeoutError())
    mock_charger()
    await _advance(hass, freezer)
    # The failed poll serves the last known value...
    assert float(hass.states.get(eid).state) == 16.0
    # ...and the log does not blame the firmware for a network timeout.
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING" and "/config" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "unsupported" not in warnings[0]

    # The limit is changed in the app; the very next poll must pick it up.
    aioclient_mock.clear_requests()
    mock_charger(config=config_payload(conf_current_limit=20))
    await _advance(hass, freezer)
    assert float(hass.states.get(eid).state) == 20.0


async def test_config_recovers(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A recovered endpoint must unlatch and resume every-tick polling."""
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/config", status=404)
    mock_charger()
    await _advance(hass, freezer)

    aioclient_mock.clear_requests()
    mock_charger(config=config_payload(conf_current_limit=20))
    for _ in range(CONFIG_REPROBE_EVERY + 1):
        await _advance(hass, freezer)

    coordinator = config_entry.runtime_data
    assert coordinator.data[DATA_CONFIG]["conf_current_limit"] == 20


async def test_rfid_404_marks_unsupported(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """A 404 is a definitive 'this firmware does not have it'."""
    mock_charger(rfid_supported=False)
    await setup_integration(hass, config_entry)
    coordinator = config_entry.runtime_data
    assert coordinator.rfid_supported is False
    assert coordinator.data[DATA_RFID_STATUS] == {}


async def test_rfid_transient_failure_stays_supported(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A timeout must not permanently hide the RFID entities.

    This is why the coordinator distinguishes unsupported from transient: a
    network blip during setup would otherwise cost the user their entities
    until the next reload.
    """
    aioclient_mock.get(f"{BASE}/status", json=status_payload())
    aioclient_mock.get(f"{BASE}/power", json=power_payload())
    aioclient_mock.get(f"{BASE}/config", json=config_payload())
    aioclient_mock.get(f"{BASE}/apiver", json={"api_files_version": 5})
    aioclient_mock.get(f"{BASE}/rfid/status", exc=TimeoutError())

    await setup_integration(hass, config_entry)
    coordinator = config_entry.runtime_data
    assert coordinator.rfid_supported is True
    # Entities exist but read unavailable until the endpoint answers.
    assert (
        hass.states.get(f"sensor.{PREFIX}_rfid_tags_stored").state == STATE_UNAVAILABLE
    )


async def test_options_change_reloads_with_new_interval(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    hass.config_entries.async_update_entry(config_entry, options={"scan_interval": 60})
    await hass.async_block_till_done()

    coordinator = config_entry.runtime_data
    assert coordinator.update_interval == timedelta(seconds=60)


async def test_unique_id_backfilled_from_charger_id(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """A legacy entry without the charger_id unique_id gets migrated."""
    mock_charger()
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, unique_id=None)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.unique_id == "000000009d104335"


def _entry_at_version(
    config_entry: MockConfigEntry, version: int, unique_id: str | None = CHARGER_ID
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        version=version,
        data=dict(config_entry.data),
    )


@pytest.mark.parametrize(
    "unique_id",
    [
        CHARGER_ID,
        # Never backfilled: the charger ID comes from /status, not the entry.
        None,
    ],
)
async def test_entity_unique_ids_rekeyed_to_charger_id(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    unique_id: str | None,
) -> None:
    """v0.3.0 keyed entities by entry ID; they move in place (VLT-2890).

    Same registry entry and entity_id, so history, customisations and
    automations are untouched, and no second set of entities appears.
    """
    mock_charger()
    entry = _entry_at_version(config_entry, 1, unique_id)
    entry.add_to_hass(hass)
    energy = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"voltie_charger_session_energy_{entry.entry_id}",
        config_entry=entry,
        suggested_object_id=f"{PREFIX}_session_energy",
    )
    # A user-chosen entity_id is the part automations depend on.
    entity_registry.async_update_entity(
        energy.entity_id, new_entity_id="sensor.ev_energy"
    )
    # The charging switch still carries its pre-v0.2 key.
    switch = entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"voltie_charger_switch_{entry.entry_id}",
        config_entry=entry,
        suggested_object_id=f"{PREFIX}_charging_enabled",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    migrated = entity_registry.async_get("sensor.ev_energy")
    assert migrated.id == energy.id
    assert migrated.unique_id == f"voltie_charger_session_energy_{CHARGER_ID}"
    assert hass.states.get("sensor.ev_energy").state == "0"
    assert hass.states.get(f"sensor.{PREFIX}_session_energy") is None
    assert (
        entity_registry.async_get(switch.entity_id).unique_id
        == f"voltie_charger_switch_{CHARGER_ID}"
    )
    assert hass.states.get(switch.entity_id).state == "on"
    unique_ids = [
        e.unique_id
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    ]
    assert all(uid.endswith(f"_{CHARGER_ID}") for uid in unique_ids)


async def test_new_entities_are_keyed_by_charger_id(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    unique_ids = [
        e.unique_id
        for e in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    ]
    assert unique_ids
    assert all(uid.endswith(f"_{CHARGER_ID}") for uid in unique_ids)
    assert not any(config_entry.entry_id in uid for uid in unique_ids)


async def test_readded_charger_gets_its_entities_back(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Removing and re-adding a charger restores its entities (VLT-2890).

    HA keeps deleted entities for 30 days and restores entity_id, registry ID
    and customisations for a matching unique_id, which an entry-keyed ID
    changes on every re-add.
    """
    mock_charger()
    await setup_integration(hass, config_entry)
    original = entity_registry.async_get(f"sensor.{PREFIX}_session_energy")
    entity_registry.async_update_entity(
        original.entity_id, new_entity_id="sensor.ev_energy", name="EV energy"
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("sensor.ev_energy") is None

    readded = _entry_at_version(config_entry, 2)
    await setup_integration(hass, readded)

    restored = entity_registry.async_get("sensor.ev_energy")
    assert restored is not None
    assert restored.id == original.id
    assert restored.name == "EV energy"
    assert restored.config_entry_id == readded.entry_id
    assert hass.states.get(f"sensor.{PREFIX}_session_energy") is None


async def test_entry_from_a_newer_release_is_refused(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """Loading a format this release cannot read would corrupt the registry."""
    mock_charger()
    entry = _entry_at_version(config_entry, 3)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_rekey_leaves_a_unique_id_that_is_already_taken(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A clash must not fail setup; the registry refuses duplicate IDs."""
    mock_charger()
    entry = _entry_at_version(config_entry, 1)
    entry.add_to_hass(hass)
    legacy = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"voltie_charger_session_energy_{entry.entry_id}",
        config_entry=entry,
        suggested_object_id=f"{PREFIX}_session_energy",
    )
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"voltie_charger_session_energy_{CHARGER_ID}",
        suggested_object_id="leftover_session_energy",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entity_registry.async_get(legacy.entity_id).unique_id == legacy.unique_id
    assert "Not migrating" in caplog.text


async def test_config_write_refreshes_outside_the_lock(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Two rapid writes must both reach the charger (VLT-2120 L5)."""
    mock_charger()
    await setup_integration(hass, config_entry)
    aioclient_mock.clear_requests()
    mock_charger()

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": f"switch.{PREFIX}_buzzer"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": f"switch.{PREFIX}_buzzer"},
        blocking=True,
    )
    puts = [c for c in aioclient_mock.mock_calls if c[0] == "PUT"]
    assert [p[2] for p in puts] == [
        {"conf_buzzer_enabled": True},
        {"conf_buzzer_enabled": False},
    ]


async def test_diagnostics_redacts_credentials(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    from homeassistant.components.diagnostics import REDACTED

    from custom_components.voltie_charger.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    mock_charger()
    await setup_integration(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["entry"]["data"]["host"] == REDACTED
    assert result["coordinator"]["data"]["status"]["charger_id"] == REDACTED


async def test_diagnostics_redacts_account_identifiers(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """The active CDR's owner and user are Voltie account IDs (VLT-2890).

    Diagnostics get attached to public GitHub issues, so none of the CDR's
    identifiers may survive anywhere in the download.
    """
    from homeassistant.components.diagnostics import REDACTED

    from custom_components.voltie_charger.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    cdr = cdr_payload()
    mock_charger(status=status_payload(evse_state=3, is_car_connected=True, cdr=cdr))
    await setup_integration(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)

    redacted = result["coordinator"]["data"]["status"]["cdr"]
    for key in ("owner", "user", "charger_id", "idtag", "idtag_name"):
        assert redacted[key] == REDACTED, key
    # Session figures are what makes the download useful, so they stay.
    assert redacted["chg_energy"] == cdr["chg_energy"]

    dump = json.dumps(result)
    for value in (cdr["owner"], cdr["user"], cdr["idtag"], cdr["idtag_name"]):
        assert value not in dump
    assert CHARGER_ID not in dump


@pytest.mark.parametrize("error_status", [500, 502])
async def test_rfid_status_server_error_is_transient(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    error_status: int,
) -> None:
    """5xx must not be mistaken for 'endpoint missing'."""
    aioclient_mock.get(f"{BASE}/status", json=status_payload())
    aioclient_mock.get(f"{BASE}/power", json=power_payload())
    aioclient_mock.get(f"{BASE}/config", json=config_payload())
    aioclient_mock.get(f"{BASE}/apiver", json={"api_files_version": 5})
    aioclient_mock.get(f"{BASE}/rfid/status", status=error_status)

    await setup_integration(hass, config_entry)
    assert config_entry.runtime_data.rfid_supported is True


async def test_rfid_status_is_not_carried_forward(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Live state must blank on failure, not linger.

    /rfid/status carries learn_in_progress and learn_to_sec. Carrying a stale
    copy forward the way /config does would keep claiming the charger is in
    learn mode with 25 s left long after it stopped.
    """
    from .conftest import rfid_status_payload

    mock_charger(
        rfid_status=rfid_status_payload(learn_in_progress=True, learn_to_sec=25)
    )
    await setup_integration(hass, config_entry)
    assert hass.states.get(f"binary_sensor.{PREFIX}_rfid_learn_mode").state == "on"

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/rfid/status", exc=TimeoutError())
    mock_charger()
    await _advance(hass, freezer)

    assert (
        hass.states.get(f"binary_sensor.{PREFIX}_rfid_learn_mode").state
        == STATE_UNAVAILABLE
    )
    assert (
        hass.states.get(f"sensor.{PREFIX}_rfid_learn_time_remaining").state
        == STATE_UNAVAILABLE
    )
    # ...and the endpoint keeps being polled, unlike /config's latch.
    assert config_entry.runtime_data.rfid_supported is True


async def test_rfid_status_keeps_polling_after_transient_failure(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A live-state endpoint must not be latched off by a network blip."""
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/rfid/status", exc=TimeoutError())
    mock_charger()
    await _advance(hass, freezer)

    def rfid_calls() -> int:
        return len(
            [c for c in aioclient_mock.mock_calls if c[1].path == "/rfid/status"]
        )

    before = rfid_calls()
    for _ in range(3):
        await _advance(hass, freezer)
    assert rfid_calls() >= before + 3


async def test_rfid_status_recovers_without_waiting_for_the_reprobe(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/rfid/status", exc=TimeoutError())
    mock_charger()
    await _advance(hass, freezer)
    assert (
        hass.states.get(f"sensor.{PREFIX}_rfid_tags_stored").state == STATE_UNAVAILABLE
    )

    aioclient_mock.clear_requests()
    mock_charger()
    await _advance(hass, freezer)
    assert hass.states.get(f"sensor.{PREFIX}_rfid_tags_stored").state == "5"


async def test_stale_hw_version_is_cleared_on_upgrade(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry, device_registry
) -> None:
    """v0.2.x wrote the EVSE firmware into hw_version; upgrades must drop it.

    The registry keeps a field once written, so no longer reporting it is not
    enough — verified on a real 2026.7.4 install where the value survived until
    this migration ran.
    """
    from custom_components.voltie_charger.const import DOMAIN

    from .conftest import CHARGER_ID

    mock_charger()
    config_entry.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, CHARGER_ID)},
        manufacturer="Voltie",
        name="Voltie Charger 4335",
        sw_version="1.3.25",
        hw_version="1.99",
    )
    assert (
        charger_device(device_registry, config_entry).hw_version
        == "1.99"
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    device = charger_device(device_registry, config_entry)
    assert device.hw_version is None
    assert device.sw_version == "1.3.25 (EVSE 1.99)"
