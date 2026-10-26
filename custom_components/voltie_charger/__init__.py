"""The Voltie Charger integration."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    VoltieChargerAuthError,
    VoltieChargerClient,
    VoltieChargerConnectionError,
    VoltieChargerError,
    VoltieChargerRejectedError,
    VoltieChargerUnsupportedError,
)
from .const import (
    API_PORT,
    CONFIG_REPROBE_EVERY,
    DATA_CONFIG,
    DATA_POWER,
    DATA_RFID_STATUS,
    DATA_STATUS,
    DOMAIN,
    LEGACY_ISSUES,
    LEGACY_UNIQUE_ID_PREFIX,
    PLATFORMS,
    REMOVED_ENTITY_KEYS,
    RENAMED_ENTITY_KEYS,
    SCAN_INTERVAL,
    UPDATE_RETRY_BACKOFF_S,
    UPDATE_RETRY_COUNT,
)
from .services import async_setup_services
from .session import SessionTracker

_LOGGER = logging.getLogger(__name__)

type VoltieChargerConfigEntry = ConfigEntry[VoltieChargerCoordinator]

CARRY_FORWARD_FIELDS = (
    "evse_state",
    "is_car_connected",
    "is_charging",
    "charge_enabled",
)


class _SoftFailProbe:
    """Latch for an endpoint the firmware may not implement.

    Once the charger has said the endpoint does not exist, it is only re-probed
    every CONFIG_REPROBE_EVERY ticks, so firmware that lacks it costs one
    request rather than one per poll.

    Any other failure is transient and retried on the next tick. Latching those
    too meant a single timeout stopped /config polling for the whole re-probe
    window, ten minutes at the default interval, while the entities kept
    presenting the old values as current.

    `carry_forward` distinguishes configuration from live state: it serves the
    last known values while the endpoint is failing.
    """

    def __init__(self, label: str, *, carry_forward: bool) -> None:
        self.label = label
        self.carry_forward = carry_forward
        # True once the charger has told us it does not implement this at all
        # (HTTP 404/405 or error_code 24), as opposed to a transient failure.
        self.unsupported = False
        self._polls_since_failure = 0
        self._logged_failure = False

    def should_try(self) -> bool:
        if not self.unsupported:
            return True
        if self._polls_since_failure >= CONFIG_REPROBE_EVERY:
            return True
        self._polls_since_failure += 1
        return False

    def mark_failure(self, *, unsupported: bool) -> bool:
        """Record a failure. Returns True the first time it is worth logging."""
        if unsupported:
            self.unsupported = True
            self._polls_since_failure = 0
        should_log = not self._logged_failure
        self._logged_failure = True
        return should_log

    def mark_success(self) -> bool:
        """Record a success. Returns True if the endpoint just recovered."""
        recovered = self._logged_failure
        self.unsupported = False
        self._polls_since_failure = 0
        self._logged_failure = False
        return recovered


class VoltieChargerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the charger's status, power, config and RFID status endpoints."""

    charger_id: str

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VoltieChargerConfigEntry,
        client: VoltieChargerClient,
    ) -> None:
        self.client = client
        self.entry = entry
        # Read once at setup, for diagnostics.
        self.api_version: int | None = None
        self.session_tracker = SessionTracker(hass, entry.entry_id)
        # The last session that ended, for the event entity to report once.
        self.finished_session: dict[str, Any] | None = None
        self._software_version: Any = None
        self._reload_scheduled = False
        self._config_lock = asyncio.Lock()
        # Configuration changes rarely, so the last known values stay useful
        # while a poll fails.
        self._config_probe = _SoftFailProbe(DATA_CONFIG, carry_forward=True)
        # RFID status is live state (learn_in_progress, learn_to_sec): a stale
        # copy would claim the charger is still learning long after it stopped,
        # so failures blank it.
        self._rfid_probe = _SoftFailProbe("rfid/status", carry_forward=False)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    @property
    def rfid_supported(self) -> bool:
        """Whether the charger implements the v5 /rfid endpoints.

        Only False once the charger has positively told us the endpoint does not
        exist; a transient failure keeps the entities in place so they recover
        instead of silently disappearing.
        """
        return not self._rfid_probe.unsupported

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self._fetch_with_retry(
                self.client.async_get_status, "/status"
            )
        except VoltieChargerAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except (VoltieChargerConnectionError, VoltieChargerRejectedError) as exc:
            raise UpdateFailed(f"/status failed: {exc}") from exc

        power: dict[str, Any]
        try:
            power = await self._fetch_with_retry(
                self.client.async_get_power, "/power"
            )
        except VoltieChargerAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except (VoltieChargerConnectionError, VoltieChargerRejectedError) as exc:
            _LOGGER.debug("/power carry-forward after: %s", exc)
            power = self._previous(DATA_POWER)

        config = await self._fetch_optional(
            self._config_probe,
            self.client.async_get_config,
            DATA_CONFIG,
            "likely unsupported by firmware",
        )
        rfid_status = await self._fetch_optional(
            self._rfid_probe,
            self.client.async_get_rfid_status,
            DATA_RFID_STATUS,
            "requires API v5 firmware",
        )

        self._carry_forward_flaky_fields(status)
        self._reload_on_software_change(status)
        # Last, so a session end is only reported from a poll that succeeded:
        # an event written while the entity is unavailable gets swallowed by
        # automations that, as recommended, ignore changes from unavailable.
        if finished := await self.session_tracker.async_update(
            status, self._async_fetch_cdr
        ):
            self.finished_session = finished
        return {
            DATA_STATUS: status,
            DATA_POWER: power,
            DATA_CONFIG: config,
            DATA_RFID_STATUS: rfid_status,
        }

    async def _async_fetch_cdr(self, cdr_id: int) -> dict[str, Any] | None:
        return await self._fetch_with_retry(
            lambda: self.client.async_get_cdr(cdr_id), "/cdr"
        )

    def _reload_on_software_change(self, status: dict[str, Any]) -> None:
        """Reload once the charger's software changes.

        The API version, the RFID endpoints and the meter reading are probed
        at setup only, so without this a firmware update would leave its new
        entities missing until the next restart.
        """
        version = status.get("sw_ver")
        if version is None or self._reload_scheduled:
            return
        if self._software_version is None:
            self._software_version = version
        elif version != self._software_version:
            _LOGGER.info(
                "Charger software changed from %s to %s; reloading to pick up "
                "its features",
                self._software_version,
                version,
            )
            # Only once: the reload replaces this coordinator.
            self._reload_scheduled = True
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        # Before a reload's new coordinator reads it back.
        await self.session_tracker.async_flush()

    def _previous(self, key: str) -> dict[str, Any]:
        return (self.data or {}).get(key, {}) or {}

    async def _fetch_optional(
        self,
        probe: _SoftFailProbe,
        fetch: Callable[[], Awaitable[dict[str, Any]]],
        data_key: str,
        hint: str,
    ) -> dict[str, Any]:
        """Fetch an endpoint the firmware may not implement, latching failures."""
        stale = self._previous(data_key) if probe.carry_forward else {}
        if not probe.should_try():
            return stale

        try:
            result = await self._fetch_with_retry(fetch, f"/{probe.label}")
        except VoltieChargerAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except (VoltieChargerConnectionError, VoltieChargerRejectedError) as exc:
            unsupported = isinstance(exc, VoltieChargerUnsupportedError)
            if probe.mark_failure(unsupported=unsupported):
                # The firmware hint only fits a definitive "not implemented";
                # a timeout on current firmware must not blame its version.
                _LOGGER.warning(
                    "Could not fetch /%s (%s): %s",
                    probe.label,
                    hint if unsupported else "retrying on the next poll",
                    exc,
                )
            return stale

        if probe.mark_success():
            _LOGGER.info("Voltie /%s is responding again", probe.label)
        return result

    async def _fetch_with_retry(self, func, label: str) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(UPDATE_RETRY_COUNT + 1):
            try:
                return await func()
            except VoltieChargerAuthError:
                raise
            except VoltieChargerUnsupportedError:
                # A missing endpoint or command will not appear on a retry.
                raise
            except (
                VoltieChargerConnectionError,
                VoltieChargerRejectedError,
            ) as exc:
                last_exc = exc
                if attempt < UPDATE_RETRY_COUNT:
                    _LOGGER.debug("Retry %d on %s: %s", attempt + 1, label, exc)
                    await asyncio.sleep(UPDATE_RETRY_BACKOFF_S)
        assert last_exc is not None
        raise last_exc

    def _carry_forward_flaky_fields(self, status: dict[str, Any]) -> None:
        """Hold the last known value for fields the charger sometimes drops."""
        prev = (self.data or {}).get(DATA_STATUS) or {}
        for field in CARRY_FORWARD_FIELDS:
            if status.get(field) is None and prev.get(field) is not None:
                status[field] = prev[field]

    async def async_push_config(self, values: dict[str, Any]) -> None:
        """Write config values; serialised to avoid racing concurrent writes.

        Auth failures deliberately propagate as VoltieChargerAuthError so the
        calling entity can report something actionable. The next poll raises
        ConfigEntryAuthFailed and starts the reauth flow.
        """
        async with self._config_lock:
            await self.client.async_set_config(values)

        # async_set_config already verified the charger accepted every value, so
        # reflect them immediately. async_request_refresh is debounced, and with
        # 17 writable config entities a burst of edits would otherwise leave the
        # later ones showing their pre-write value for the whole cooldown.
        #
        # Updated in place rather than via async_set_updated_data, which cancels
        # the debouncer: that would make every write trigger a full four-endpoint
        # poll immediately, so dragging a number entity would hammer the charger.
        if self.data:
            self.data[DATA_CONFIG] = {
                **(self.data.get(DATA_CONFIG) or {}),
                **values,
            }
            self.async_update_listeners()

        # Refresh outside the lock so a queued write isn't serialised behind
        # the full multi-endpoint poll.
        await self.async_request_refresh()


# The integration is config-entry only; this makes HA reject a stray
# `voltie_charger:` YAML block instead of silently ignoring it.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's device-targeted services once."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> bool:
    # First, so this happens even while the charger is unreachable.
    _delete_legacy_issues(hass, entry)
    _migrate_entry_data(hass, entry)

    session = async_get_clientsession(hass)
    client = VoltieChargerClient(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME) or None,
        entry.data.get(CONF_PASSWORD) or None,
        port=entry.data[CONF_PORT],
    )

    coordinator = VoltieChargerCoordinator(hass, entry, client)
    # Before the first refresh, which already compares against it.
    await coordinator.session_tracker.async_load()

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except UpdateFailed as exc:
        raise ConfigEntryNotReady(str(exc)) from exc

    charger_id = (coordinator.data or {}).get(DATA_STATUS, {}).get("charger_id")
    if not charger_id:
        raise ConfigEntryNotReady("Charger did not return a charger_id yet")

    coordinator.charger_id = charger_id
    coordinator.api_version = await _async_probe_api_version(client)

    if entry.unique_id != charger_id:
        _migrate_unique_id(hass, entry, charger_id)
    _migrate_title(hass, entry, charger_id)

    _migrate_device_identifier(hass, entry.entry_id, charger_id)
    _clear_stale_hw_version(hass, entry.entry_id, charger_id)
    # Before the platforms load, so each entity finds its existing registry
    # entry instead of registering a duplicate beside it.
    _migrate_entities(hass, entry, charger_id)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_probe_api_version(client: VoltieChargerClient) -> int | None:
    """Read /apiver once, for diagnostics; old firmware lacks it."""
    try:
        return await client.async_get_apiver()
    except VoltieChargerError as exc:
        _LOGGER.debug("Could not read /apiver: %s", exc)
        return None


def _delete_legacy_issues(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> None:
    """Delete the repair issues v0.4.0 raised; this release raises none.

    The built-in integration has neither, and with their strings gone, an
    issue left behind would show raw translation keys.
    """
    for kind in LEGACY_ISSUES:
        ir.async_delete_issue(hass, DOMAIN, f"{kind}_{entry.entry_id}")


def _migrate_entry_data(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> None:
    """Give the entry the data the built-in integration reads, and no options.

    It reads host, port, username and password, and requires the port, which
    entries from discovery and from releases before the port setting lack.
    Empty credentials are fine: both integrations treat them as none. The one
    option there ever was, the polling interval, is gone.
    """
    data = dict(entry.data)
    data[CONF_PORT] = _port(data.get(CONF_PORT))
    for key in (CONF_USERNAME, CONF_PASSWORD):
        if data.get(key) is None:
            data[key] = ""
    if data != entry.data or entry.options:
        hass.config_entries.async_update_entry(entry, data=data, options={})


def _port(value: Any) -> int:
    """The stored port as an int, or the default if it is missing or invalid."""
    if isinstance(value, bool):
        return API_PORT
    try:
        port = int(value)
    except (TypeError, ValueError):
        return API_PORT
    return port if 0 < port < 65536 else API_PORT


def _find_device(
    hass: HomeAssistant, entry_id: str, identifier: tuple[str, str]
) -> dr.DeviceEntry | None:
    """Look a device up by identifier, the way the running release wants.

    Home Assistant 2026.9 deprecated async_get_device(identifiers=...), since
    identifiers stopped being unique across config entries, in favour of a
    lookup scoped to one entry. Older releases, which the manifest still
    supports, lack the replacement, but their identifiers are globally unique,
    so the plain lookup there is exact.
    """
    dev_reg = dr.async_get(hass)
    if hasattr(dev_reg, "async_get_device_by_identifier"):
        return dev_reg.async_get_device_by_identifier(identifier, entry_id)
    return dev_reg.async_get_device(identifiers={identifier})


async def async_unload_entry(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> None:
    """Remove what outlives the entry.

    That is its session store, and any repair issue an older release left on
    an entry that was not set up since.
    """
    _delete_legacy_issues(hass, entry)
    await SessionTracker(hass, entry.entry_id).async_remove()


async def async_migrate_entry(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> bool:
    """Bring a config entry up to the current version.

    Version 2 keys entity unique IDs by charger ID. The re-keying itself runs
    in async_setup_entry, where /status provides the charger ID; the bump is
    what makes an older release refuse the entry rather than register a second,
    entry-keyed set of entities next to the migrated ones.
    """
    if entry.version > 2:
        # Downgraded from a release this one cannot read.
        return False
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


def _migrate_unique_id(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry, charger_id: str
) -> None:
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and other.unique_id == charger_id:
            _LOGGER.warning(
                "Skipping unique_id migration for %s: %s is already in use",
                entry.entry_id,
                charger_id,
            )
            return
    hass.config_entries.async_update_entry(entry, unique_id=charger_id)


# The title every earlier release gave a new entry: "Voltie Charger (<host>)".
_OLD_DEFAULT_TITLE = re.compile(r"Voltie Charger \(.+\)")


def _migrate_title(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry, charger_id: str
) -> None:
    """Give an entry with the old default title the one new entries get.

    The built-in integration names the device after the entry, so the old
    title would rename the device, and with it every entity's friendly name,
    to "Voltie Charger (192.168.1.50)" on the move. The new title is the
    device name this integration already shows. A title the user chose stays.
    """
    if _OLD_DEFAULT_TITLE.fullmatch(entry.title):
        hass.config_entries.async_update_entry(entry, title=entry_title(charger_id))


def entry_title(charger_id: str) -> str:
    """The title of a new entry, the same as the built-in integration's."""
    return f"Voltie Charger {charger_id[-4:].lower()}"


def _migrate_device_identifier(
    hass: HomeAssistant, entry_id: str, charger_id: str
) -> None:
    """Migrate legacy entry_id-keyed devices to the real charger_id identifier."""
    if entry_id == charger_id:
        return
    old = _find_device(hass, entry_id, (DOMAIN, entry_id))
    if not old:
        return
    if _find_device(hass, entry_id, (DOMAIN, charger_id)):
        return
    dr.async_get(hass).async_update_device(
        old.id, new_identifiers={(DOMAIN, charger_id)}
    )


def _parse_unique_id(
    unique_id: str, charger_id: str, entry_id: str
) -> tuple[int, str] | None:
    """Split an entity unique ID into (format rank, key); None if foreign.

    Rank 0 is the current "{charger_id}_{key}", 1 is v0.4.0's
    "voltie_charger_{key}_{charger_id}" and 2 is v0.3.0's
    "voltie_charger_{key}_{entry_id}". Keys contain underscores, so the key is
    what remains once the known prefix and the known suffix are stripped.
    """
    if unique_id.startswith(f"{charger_id}_"):
        key = unique_id.removeprefix(f"{charger_id}_")
        return (0, key) if key else None
    if not unique_id.startswith(LEGACY_UNIQUE_ID_PREFIX):
        return None
    rest = unique_id.removeprefix(LEGACY_UNIQUE_ID_PREFIX)
    for rank, suffix in ((1, charger_id), (2, entry_id)):
        if len(rest) > len(suffix) + 1 and rest.endswith(f"_{suffix}"):
            return rank, rest.removesuffix(f"_{suffix}")
    return None


@callback
def _migrate_entities(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry, charger_id: str
) -> None:
    """Re-key entity unique IDs to "{charger_id}_{key}", the built-in format.

    The built-in integration has no migration code, so this leaves the
    registry the way it expects it. Each entity is re-keyed in place, which
    keeps its entity_id and with it history, customisations and automations.
    The debug sensors the built-in one lacks are removed, not left as
    orphans. Running it again changes nothing.
    """
    ent_reg = er.async_get(hass)
    rekeys: list[tuple[int, str, str, str]] = []
    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        parsed = _parse_unique_id(entity_entry.unique_id, charger_id, entry.entry_id)
        if parsed is None:
            continue
        rank, key = parsed
        key = RENAMED_ENTITY_KEYS.get(key, key)
        if key in REMOVED_ENTITY_KEYS:
            _LOGGER.debug("Removing %s, no longer provided", entity_entry.entity_id)
            ent_reg.async_remove(entity_entry.entity_id)
            continue
        new_unique_id = f"{charger_id}_{key}"
        if new_unique_id != entity_entry.unique_id:
            rekeys.append(
                (rank, entity_entry.entity_id, entity_entry.domain, new_unique_id)
            )

    # Newer formats first: should two entries claim one key, the newer wins.
    for _rank, entity_id, domain, new_unique_id in sorted(rekeys):
        if taken_by := ent_reg.async_get_entity_id(domain, DOMAIN, new_unique_id):
            # Only possible with two entries for one charger; leave it rather
            # than fail setup over a duplicate the user has to remove anyway.
            _LOGGER.warning(
                "Not migrating %s to unique_id %s: %s already uses it",
                entity_id,
                new_unique_id,
                taken_by,
            )
            continue
        ent_reg.async_update_entity(entity_id, new_unique_id=new_unique_id)


def _clear_stale_hw_version(
    hass: HomeAssistant, entry_id: str, charger_id: str
) -> None:
    """Drop the hw_version earlier versions set from the EVSE firmware number.

    The registry keeps a field once written, so simply no longer reporting it
    leaves upgraded installs showing a "Hardware" value that is really the EVSE
    firmware, the mislabelling this was meant to remove. Both versions now live
    in sw_version instead.
    """
    device = _find_device(hass, entry_id, (DOMAIN, charger_id))
    if device is not None and device.hw_version is not None:
        dr.async_get(hass).async_update_device(device.id, hw_version=None)


__all__ = [
    "VoltieChargerConfigEntry",
    "VoltieChargerCoordinator",
    "VoltieChargerError",
    "entry_title",
]
