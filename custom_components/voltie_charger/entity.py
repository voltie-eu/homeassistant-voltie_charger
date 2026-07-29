"""Shared base entities."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import VoltieChargerCoordinator
from .const import (
    DATA_CONFIG,
    DATA_RFID_STATUS,
    DATA_STATUS,
    DEFAULT_MODEL,
    DOMAIN,
    MANUFACTURER,
)

_MDNS_SUFFIX_RE = re.compile(r"voltiecharger-([0-9a-f]+)", re.IGNORECASE)


def _format_sw_version(raw: Any) -> str | None:
    """Decode the decimal-packed software version (e.g. 1001036 -> '1.1.36')."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    major = value // 1_000_000
    minor = (value // 1_000) % 1_000
    patch = value % 1_000
    return f"{major}.{minor}.{patch}"


def _format_fw_version(raw: Any) -> str | None:
    """Decode the decimal-packed firmware version (e.g. 105 -> '1.05').

    The minor part is zero-padded to match the firmware's own %d.%02d
    formatting.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return f"{value // 100}.{value % 100:02d}"


def _format_versions(status: dict[str, Any]) -> str | None:
    """Combine software + EVSE firmware versions for DeviceInfo.

    DeviceInfo has no dedicated firmware field and the frontend labels
    sw_version as "Firmware", so both go there; hw_version would mislabel
    the MCU firmware as hardware.
    """
    sw = _format_sw_version(status.get("sw_ver"))
    fw = _format_fw_version(status.get("fw_ver"))
    if sw and fw:
        return f"{sw} (EVSE {fw})"
    return sw or (f"EVSE {fw}" if fw else None)


def _display_suffix(host: str, charger_id: str) -> str:
    """Return the 4-char suffix used in the display name.

    Prefers the MAC-derived mDNS hostname suffix since that's what's printed
    on the charger's physical label; falls back to the last 4 of charger_id
    for manually-added chargers.
    """
    if match := _MDNS_SUFFIX_RE.match(host):
        return match.group(1).lower()
    return charger_id[-4:] if charger_id else ""


class VoltieChargerEntity(CoordinatorEntity[VoltieChargerCoordinator]):
    """Base entity with shared device_info and coordinator data accessors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VoltieChargerCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"voltie_charger_{key}_{coordinator.entry.entry_id}"

    @property
    def _status(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(DATA_STATUS) or {}

    @property
    def _config(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(DATA_CONFIG) or {}

    @property
    def _rfid_status(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(DATA_RFID_STATUS) or {}

    @property
    def device_info(self) -> DeviceInfo:
        charger_id = self.coordinator.charger_id
        status = self._status
        host = self.coordinator.entry.data.get(CONF_HOST, "")
        suffix = _display_suffix(host, charger_id)

        client = self.coordinator.client
        return DeviceInfo(
            identifiers={(DOMAIN, charger_id)},
            manufacturer=MANUFACTURER,
            model=DEFAULT_MODEL,
            name=f"Voltie Charger {suffix}".rstrip(),
            serial_number=charger_id,
            sw_version=_format_versions(status),
            configuration_url=f"http://{client.host}:{client.port}",
        )


class VoltieChargerConfigEntity(VoltieChargerEntity):
    """Entity backed by a writable key in /config.

    Hardware- and firmware-dependent keys are simply absent from the /config
    response, so key presence is what decides availability.
    """

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
        key: str,
        config_key: str,
    ) -> None:
        super().__init__(coordinator, key)
        self._config_key = config_key

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self._config_key in self._config

    @property
    def _raw_value(self) -> Any:
        return self._config.get(self._config_key)


class VoltieChargerRfidEntity(VoltieChargerEntity):
    """Entity backed by /rfid/status, which only exists on API v5 firmware."""

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return bool(self._rfid_status)
