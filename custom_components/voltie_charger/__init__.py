"""The Voltie Charger integration."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
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
    CONF_SCAN_INTERVAL,
    CONFIG_REPROBE_EVERY,
    DATA_CONFIG,
    DATA_POWER,
    DATA_RFID_STATUS,
    DATA_STATUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    UPDATE_RETRY_BACKOFF_S,
    UPDATE_RETRY_COUNT,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

type VoltieChargerConfigEntry = ConfigEntry[VoltieChargerCoordinator]

CARRY_FORWARD_FIELDS = (
    "evse_state",
    "is_car_connected",
    "is_charging",
    "charge_enabled",
)


class _SoftFailProbe:
    """Availability latch for an endpoint the firmware may not implement.

    Once latched, the endpoint is only re-probed every CONFIG_REPROBE_EVERY
    ticks, so firmware that lacks it costs one request rather than one per poll.

    The two policy flags distinguish configuration from live state:
    `carry_forward` serves the last known values on failure, and
    `latch_transient` also stops polling after an ordinary failure rather than
    only after a definitive "not implemented".
    """

    def __init__(
        self, label: str, *, carry_forward: bool, latch_transient: bool
    ) -> None:
        self.label = label
        self.carry_forward = carry_forward
        self.latch_transient = latch_transient
        self.available = True
        # True once the charger has told us it does not implement this at all
        # (HTTP 404/405 or error_code 24) — as opposed to a transient failure.
        self.unsupported = False
        self._polls_since_failure = 0
        self._logged_failure = False

    def should_try(self) -> bool:
        if self.available:
            return True
        if self._polls_since_failure >= CONFIG_REPROBE_EVERY:
            return True
        self._polls_since_failure += 1
        return False

    def mark_failure(self, *, unsupported: bool) -> bool:
        """Record a failure. Returns True the first time it is worth logging."""
        if unsupported:
            self.unsupported = True
        if unsupported or self.latch_transient:
            self.available = False
            self._polls_since_failure = 0
        should_log = not self._logged_failure
        self._logged_failure = True
        return should_log

    def mark_success(self) -> bool:
        """Record a success. Returns True if the endpoint just recovered."""
        recovered = self._logged_failure or not self.available
        self.available = True
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
        self.api_version: int | None = None
        self._config_lock = asyncio.Lock()
        # Configuration changes rarely, so the last known values stay useful and
        # a flaky endpoint is not worth polling every tick.
        self._config_probe = _SoftFailProbe(
            DATA_CONFIG, carry_forward=True, latch_transient=True
        )
        # RFID status is live state (learn_in_progress, learn_to_sec): a stale
        # copy would claim the charger is still learning long after it stopped,
        # so failures blank it and polling continues unless the endpoint is
        # genuinely absent.
        self._rfid_probe = _SoftFailProbe(
            "rfid/status", carry_forward=False, latch_transient=False
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=_scan_interval(entry),
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
        return {
            DATA_STATUS: status,
            DATA_POWER: power,
            DATA_CONFIG: config,
            DATA_RFID_STATUS: rfid_status,
        }

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
                _LOGGER.warning(
                    "Could not fetch /%s (%s): %s", probe.label, hint, exc
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


def _scan_interval(entry: VoltieChargerConfigEntry) -> timedelta:
    seconds = entry.options.get(CONF_SCAN_INTERVAL)
    if isinstance(seconds, (int, float)) and seconds > 0:
        return timedelta(seconds=int(seconds))
    return DEFAULT_SCAN_INTERVAL


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
    session = async_get_clientsession(hass)
    client = VoltieChargerClient(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
        port=entry.data.get(CONF_PORT) or API_PORT,
    )

    coordinator = VoltieChargerCoordinator(hass, entry, client)

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

    _migrate_device_identifier(hass, entry.entry_id, charger_id)
    _clear_stale_hw_version(hass, charger_id)

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_probe_api_version(client: VoltieChargerClient) -> int | None:
    """Read /apiver once. Absent on old firmware, so failure is not fatal."""
    try:
        return await client.async_get_apiver()
    except VoltieChargerError as exc:
        _LOGGER.debug("Could not read /apiver: %s", exc)
        return None


async def async_unload_entry(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


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


def _migrate_device_identifier(
    hass: HomeAssistant, entry_id: str, charger_id: str
) -> None:
    """Migrate legacy entry_id-keyed devices to the real charger_id identifier."""
    if entry_id == charger_id:
        return
    dev_reg = dr.async_get(hass)
    old = dev_reg.async_get_device(identifiers={(DOMAIN, entry_id)})
    if not old:
        return
    if dev_reg.async_get_device(identifiers={(DOMAIN, charger_id)}):
        return
    dev_reg.async_update_device(
        old.id, new_identifiers={(DOMAIN, charger_id)}
    )


def _clear_stale_hw_version(hass: HomeAssistant, charger_id: str) -> None:
    """Drop the hw_version earlier versions set from the EVSE firmware number.

    The registry keeps a field once written, so simply no longer reporting it
    leaves upgraded installs showing a "Hardware" value that is really the EVSE
    firmware — the mislabelling this was meant to remove. Both versions now live
    in sw_version instead.
    """
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, charger_id)})
    if device is not None and device.hw_version is not None:
        dev_reg.async_update_device(device.id, hw_version=None)


__all__ = [
    "VoltieChargerConfigEntry",
    "VoltieChargerCoordinator",
    "VoltieChargerError",
]
