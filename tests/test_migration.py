"""The move to the built-in integration's registry layout (v0.5.0).

The built-in integration has no migration code. It reads the same config
entry (version 2) and expects entity unique IDs "{charger_id}_{key}", so this
release must leave everything that way, and keep each entity_id while doing
it, since history, dashboards and automations follow the entity_id.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.voltie_charger.const import DOMAIN

from .conftest import BASE, CHARGER_ID, HOST, PORT, setup_integration

PREFIX = "voltie_charger_4335"

V040 = "voltie_charger_{key}_" + CHARGER_ID
V030 = "voltie_charger_{key}_{entry_id}"

# (platform, key in that release, key now, object_id an install had)
LEGACY_ENTITIES = [
    ("sensor", "session_energy", "session_energy", "session_energy"),
    # Keys with underscores, one ending in another key ("current_l1").
    ("sensor", "dlm_current_l1", "dlm_current_l1", "dlm_current_l1"),
    ("sensor", "current_l1", "current_l1", "current_l1"),
    ("sensor", "phases", "phases", "phases_in_use"),
    ("binary_sensor", "is_charging", "is_charging", "charging"),
    ("binary_sensor", "problem", "problem", "problem"),
    # The charging switch's key from before v0.2.
    ("switch", "switch", "charging", "charging_enabled"),
    ("number", "dlm_current_limit", "dlm_current_limit", "building_current_limit"),
    ("button", "rfid_learn_cancel", "rfid_learn_cancel", "cancel_rfid_learn_mode"),
    ("event", "charging_session", "charging_session", "charging_session"),
]
DROPPED = ["api_version", "rfid_list_hash", "rfid_list_format_ver"]


def _entry(
    config_entry: MockConfigEntry,
    *,
    version: int = 2,
    unique_id: str | None = CHARGER_ID,
    **kwargs,
) -> MockConfigEntry:
    kwargs.setdefault("data", dict(config_entry.data))
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        version=version,
        title=kwargs.pop("title", config_entry.title),
        **kwargs,
    )


def _register(
    entity_registry: er.EntityRegistry,
    entry: MockConfigEntry,
    template: str,
) -> dict[str, er.RegistryEntry]:
    """Register the legacy entities of one release, keyed by their key now."""
    registered = {}
    for platform, old_key, key, object_id in LEGACY_ENTITIES:
        registered[key] = entity_registry.async_get_or_create(
            platform,
            DOMAIN,
            template.format(key=old_key, entry_id=entry.entry_id),
            config_entry=entry,
            suggested_object_id=f"{PREFIX}_{object_id}",
        )
    for key in DROPPED:
        registered[key] = entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            template.format(key=key, entry_id=entry.entry_id),
            config_entry=entry,
            suggested_object_id=f"{PREFIX}_{key}",
        )
    return registered


def _unique_ids(entity_registry: er.EntityRegistry, entry: MockConfigEntry) -> set:
    return {
        e.unique_id
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }


def _assert_rekeyed(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    entry: MockConfigEntry,
    registered: dict[str, er.RegistryEntry],
) -> None:
    for platform, _old_key, key, _object_id in LEGACY_ENTITIES:
        old = registered[key]
        migrated = entity_registry.async_get(old.entity_id)
        # The same registry entry, so the same entity_id and history.
        assert migrated is not None, old.entity_id
        assert migrated.id == old.id
        assert migrated.unique_id == f"{CHARGER_ID}_{key}"
        assert migrated.domain == platform
        assert hass.states.get(old.entity_id) is not None
    for key in DROPPED:
        assert entity_registry.async_get(registered[key].entity_id) is None
        assert hass.states.get(registered[key].entity_id) is None

    # The format the built-in integration expects, and nothing left over.
    unique_ids = _unique_ids(entity_registry, entry)
    assert all(uid.startswith(f"{CHARGER_ID}_") for uid in unique_ids)
    # No second entity was registered beside a migrated one.
    assert hass.states.get(f"sensor.{PREFIX}_session_energy_2") is None
    assert hass.states.get(f"switch.{PREFIX}_charging_enabled_2") is None


async def test_unique_ids_rekeyed_from_v040(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """v0.4.0 used "voltie_charger_{key}_{charger_id}"."""
    mock_charger()
    entry = _entry(config_entry)
    entry.add_to_hass(hass)
    registered = _register(entity_registry, entry, V040)
    # A user-chosen entity_id is the part automations depend on.
    entity_registry.async_update_entity(
        registered["session_energy"].entity_id, new_entity_id="sensor.ev_energy"
    )
    registered["session_energy"] = entity_registry.async_get("sensor.ev_energy")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    _assert_rekeyed(hass, entity_registry, entry, registered)
    assert hass.states.get("sensor.ev_energy").state == "0"
    assert hass.states.get(f"switch.{PREFIX}_charging_enabled").state == "on"


@pytest.mark.parametrize(
    "unique_id",
    [
        CHARGER_ID,
        # Never backfilled: the charger ID comes from /status, not the entry.
        None,
    ],
)
async def test_unique_ids_rekeyed_from_v030(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    unique_id: str | None,
) -> None:
    """v0.3.0 and older used "voltie_charger_{key}_{entry_id}"."""
    mock_charger()
    entry = _entry(config_entry, version=1, unique_id=unique_id)
    entry.add_to_hass(hass)
    registered = _register(entity_registry, entry, V030)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.unique_id == CHARGER_ID
    _assert_rekeyed(hass, entity_registry, entry, registered)


async def test_migration_runs_once(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Every setup runs it; after the first, it changes nothing."""
    mock_charger()
    entry = _entry(config_entry)
    entry.add_to_hass(hass)
    _register(entity_registry, entry, V040)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    before = {
        e.id: (e.entity_id, e.unique_id)
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    after = {
        e.id: (e.entity_id, e.unique_id)
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }
    assert after == before


async def test_rekey_leaves_a_unique_id_that_is_already_taken(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A clash must not fail setup; the registry refuses duplicate IDs."""
    mock_charger()
    entry = _entry(config_entry)
    entry.add_to_hass(hass)
    legacy = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        V040.format(key="session_energy"),
        config_entry=entry,
        suggested_object_id=f"{PREFIX}_session_energy",
    )
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{CHARGER_ID}_session_energy",
        suggested_object_id="leftover_session_energy",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entity_registry.async_get(legacy.entity_id).unique_id == legacy.unique_id
    assert "Not migrating" in caplog.text


async def test_newer_format_wins_a_clash(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Should a v0.3.0 leftover sit beside its v0.4.0 successor, the latter
    keeps the entity, whatever order the registry lists them in."""
    mock_charger()
    entry = _entry(config_entry)
    entry.add_to_hass(hass)
    older = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        V030.format(key="session_energy", entry_id=entry.entry_id),
        config_entry=entry,
        suggested_object_id="old_session_energy",
    )
    newer = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        V040.format(key="session_energy"),
        config_entry=entry,
        suggested_object_id=f"{PREFIX}_session_energy",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        entity_registry.async_get(newer.entity_id).unique_id
        == f"{CHARGER_ID}_session_energy"
    )
    assert entity_registry.async_get(older.entity_id).unique_id == older.unique_id
    assert "Not migrating sensor.old_session_energy" in caplog.text


async def test_foreign_unique_ids_are_left_alone(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Only the three known formats are rewritten."""
    mock_charger()
    entry = _entry(config_entry)
    entry.add_to_hass(hass)
    foreign = [
        # Another charger's ID, after a different charger took the address.
        "voltie_charger_session_energy_00000000aaaaaaaa",
        "something_else",
        # The prefix alone, with nothing to strip.
        f"voltie_charger_{CHARGER_ID}",
    ]
    for unique_id in foreign:
        entity_registry.async_get_or_create(
            "sensor", DOMAIN, unique_id, config_entry=entry
        )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert set(foreign) <= _unique_ids(entity_registry, entry)


async def test_new_entities_are_keyed_by_charger_id(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)
    unique_ids = _unique_ids(entity_registry, config_entry)
    assert unique_ids
    assert all(uid.startswith(f"{CHARGER_ID}_") for uid in unique_ids)
    assert not any(config_entry.entry_id in uid for uid in unique_ids)
    assert not any(uid.startswith("voltie_charger_") for uid in unique_ids)


async def test_readded_charger_gets_its_entities_back(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Removing and re-adding a charger restores its entities (VLT-2890).

    HA keeps deleted entities for 30 days and restores entity_id, registry ID
    and customisations for a matching unique_id, which an entry-keyed ID
    changes on every re-add. The built-in integration relies on the same.
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

    readded = _entry(config_entry)
    await setup_integration(hass, readded)

    restored = entity_registry.async_get("sensor.ev_energy")
    assert restored is not None
    assert restored.id == original.id
    assert restored.name == "EV energy"
    assert restored.config_entry_id == readded.entry_id
    assert hass.states.get(f"sensor.{PREFIX}_session_energy") is None


async def test_unique_id_backfilled_from_charger_id(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """The built-in integration refuses an entry whose unique_id is not the
    charger ID, so a legacy entry without one gets it."""
    mock_charger()
    entry = _entry(config_entry, unique_id=None)
    await setup_integration(hass, entry)
    assert entry.unique_id == CHARGER_ID


async def test_entry_from_a_newer_release_is_refused(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """Loading a format this release cannot read would corrupt the registry."""
    mock_charger()
    entry = _entry(config_entry, version=3)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


# ---- config entry ----


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(
            {CONF_HOST: HOST},
            {CONF_HOST: HOST, CONF_PORT: PORT, CONF_USERNAME: "", CONF_PASSWORD: ""},
            id="v0.2 entry",
        ),
        pytest.param(
            {CONF_HOST: HOST, CONF_USERNAME: "", CONF_PASSWORD: ""},
            {CONF_HOST: HOST, CONF_PORT: PORT, CONF_USERNAME: "", CONF_PASSWORD: ""},
            id="from discovery",
        ),
        pytest.param(
            {CONF_HOST: HOST, CONF_PORT: None, CONF_USERNAME: "a", CONF_PASSWORD: "b"},
            {CONF_HOST: HOST, CONF_PORT: PORT, CONF_USERNAME: "a", CONF_PASSWORD: "b"},
            id="port None",
        ),
        pytest.param(
            {CONF_HOST: HOST, CONF_PORT: "5059", CONF_USERNAME: "", CONF_PASSWORD: ""},
            {CONF_HOST: HOST, CONF_PORT: PORT, CONF_USERNAME: "", CONF_PASSWORD: ""},
            id="port as text",
        ),
    ],
)
async def test_entry_data_gets_what_the_builtin_integration_reads(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    data: dict,
    expected: dict,
) -> None:
    """It requires the port, which older and discovered entries lack."""
    mock_charger()
    entry = _entry(config_entry, data=data)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert dict(entry.data) == expected
    assert isinstance(entry.data[CONF_PORT], int)


async def test_custom_port_is_kept(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    base = f"http://{HOST}:9000"
    from .conftest import config_payload, power_payload, status_payload

    aioclient_mock.get(f"{base}/status", json=status_payload())
    aioclient_mock.get(f"{base}/power", json=power_payload())
    aioclient_mock.get(f"{base}/config", json=config_payload())
    aioclient_mock.get(f"{base}/apiver", json={"api_files_version": 5})
    aioclient_mock.get(f"{base}/rfid/status", status=404)
    entry = _entry(config_entry, data={**config_entry.data, CONF_PORT: 9000})
    await setup_integration(hass, entry)
    assert entry.data[CONF_PORT] == 9000


async def test_options_are_cleared(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    """The polling interval option is gone; polling is every 30 s."""
    mock_charger()
    entry = _entry(config_entry, options={"scan_interval": 5})
    await setup_integration(hass, entry)
    assert entry.options == {}
    assert entry.runtime_data.update_interval == timedelta(seconds=30)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (f"Voltie Charger ({HOST})", "Voltie Charger 4335"),
        ("Voltie Charger (voltiecharger-4335.local)", "Voltie Charger 4335"),
        ("Voltie Charger 4335", "Voltie Charger 4335"),
        # Chosen by the user.
        ("Garage", "Garage"),
        ("Voltie Charger (garage)x", "Voltie Charger (garage)x"),
    ],
)
async def test_old_default_title_is_replaced(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    device_registry,
    title: str,
    expected: str,
) -> None:
    """The built-in integration names the device after the entry title."""
    from .conftest import charger_device

    mock_charger()
    entry = _entry(config_entry, title=title)
    await setup_integration(hass, entry)
    assert entry.title == expected
    # The device keeps its name either way.
    assert charger_device(device_registry, entry).name == "Voltie Charger 4335"


# ---- repairs ----


@pytest.mark.parametrize("reachable", [True, False])
async def test_legacy_repair_issues_are_deleted(
    hass: HomeAssistant,
    mock_charger,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    reachable: bool,
) -> None:
    """v0.4.0 raised two; their strings are gone, so they must go too."""
    if reachable:
        mock_charger()
    else:
        aioclient_mock.get(f"{BASE}/status", exc=TimeoutError())
    config_entry.add_to_hass(hass)
    other = f"outdated_firmware_{'0' * 26}"
    for issue_id in (
        f"outdated_firmware_{config_entry.entry_id}",
        f"unauthenticated_api_{config_entry.entry_id}",
        other,
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=issue_id.rsplit("_", 1)[0],
        )

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is (
        ConfigEntryState.LOADED if reachable else ConfigEntryState.SETUP_RETRY
    )
    for kind in ("outdated_firmware", "unauthenticated_api"):
        assert (
            issue_registry.async_get_issue(DOMAIN, f"{kind}_{config_entry.entry_id}")
            is None
        )
    # Another entry's issue is that entry's business.
    assert issue_registry.async_get_issue(DOMAIN, other) is not None
