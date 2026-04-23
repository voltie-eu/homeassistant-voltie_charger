"""The Voltie Charger integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    VoltieChargerAuthError,
    VoltieChargerClient,
    VoltieChargerConnectionError,
    VoltieChargerError,
    VoltieChargerRejectedError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONFIG_REPROBE_EVERY,
    DATA_CONFIG,
    DATA_POWER,
    DATA_STATUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    UPDATE_RETRY_BACKOFF_S,
    UPDATE_RETRY_COUNT,
)

_LOGGER = logging.getLogger(__name__)

type VoltieChargerConfigEntry = ConfigEntry[VoltieChargerCoordinator]

CARRY_FORWARD_FIELDS = (
    "evse_state",
    "is_car_connected",
    "is_charging",
    "charge_enabled",
)


class VoltieChargerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the charger's status, power and config endpoints."""

    charger_id: str

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VoltieChargerConfigEntry,
        client: VoltieChargerClient,
    ) -> None:
        self.client = client
        self.entry = entry
        self._config_lock = asyncio.Lock()
        # Soft-fail latch for /config; re-probed every CONFIG_REPROBE_EVERY polls.
        self._config_available = True
        self._polls_since_config_failure = 0
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=_scan_interval(entry),
        )

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
            power = (self.data or {}).get(DATA_POWER, {}) or {}

        config = await self._fetch_config_maybe()
        self._carry_forward_flaky_fields(status)
        return {DATA_STATUS: status, DATA_POWER: power, DATA_CONFIG: config}

    async def _fetch_config_maybe(self) -> dict[str, Any]:
        should_try = self._config_available or (
            self._polls_since_config_failure >= CONFIG_REPROBE_EVERY
        )
        if not should_try:
            self._polls_since_config_failure += 1
            return (self.data or {}).get(DATA_CONFIG, {}) or {}

        try:
            config = await self._fetch_with_retry(
                self.client.async_get_config, "/config"
            )
        except VoltieChargerAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except (VoltieChargerConnectionError, VoltieChargerRejectedError) as exc:
            if self._config_available:
                _LOGGER.warning(
                    "Could not fetch /config (likely unsupported by firmware): %s",
                    exc,
                )
            self._config_available = False
            self._polls_since_config_failure = 0
            return (self.data or {}).get(DATA_CONFIG, {}) or {}

        if not self._config_available:
            _LOGGER.info("Voltie /config is responding again")
            self._config_available = True
        self._polls_since_config_failure = 0
        return config

    async def _fetch_with_retry(self, func, label: str) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(UPDATE_RETRY_COUNT + 1):
            try:
                return await func()
            except VoltieChargerAuthError:
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
        """Write config values; serialised to avoid racing concurrent writes."""
        async with self._config_lock:
            try:
                await self.client.async_set_config(values)
            except VoltieChargerAuthError as exc:
                raise ConfigEntryAuthFailed(str(exc)) from exc
            await self.async_request_refresh()


def _scan_interval(entry: VoltieChargerConfigEntry) -> timedelta:
    seconds = entry.options.get(CONF_SCAN_INTERVAL)
    if isinstance(seconds, (int, float)) and seconds > 0:
        return timedelta(seconds=int(seconds))
    return DEFAULT_SCAN_INTERVAL


async def async_setup_entry(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> bool:
    session = async_get_clientsession(hass)
    client = VoltieChargerClient(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
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

    if entry.unique_id != charger_id:
        _migrate_unique_id(hass, entry, charger_id)

    _migrate_device_identifier(hass, entry.entry_id, charger_id)

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


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


__all__ = [
    "VoltieChargerConfigEntry",
    "VoltieChargerCoordinator",
    "VoltieChargerError",
]
