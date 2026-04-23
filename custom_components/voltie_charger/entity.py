"""Shared base entity."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import VoltieChargerCoordinator
from .const import DATA_STATUS, DEFAULT_MODEL, DOMAIN, MANUFACTURER

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
    """Decode the decimal-packed firmware version (e.g. 199 -> '1.99')."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return f"{value // 100}.{value % 100}"


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
    """Base entity with shared device_info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VoltieChargerCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"voltie_charger_{key}_{coordinator.entry.entry_id}"

    @property
    def device_info(self) -> DeviceInfo:
        charger_id = self.coordinator.charger_id
        status = (self.coordinator.data or {}).get(DATA_STATUS, {})
        host = self.coordinator.entry.data.get(CONF_HOST, "")
        suffix = _display_suffix(host, charger_id)

        return DeviceInfo(
            identifiers={(DOMAIN, charger_id)},
            manufacturer=MANUFACTURER,
            model=DEFAULT_MODEL,
            name=f"Voltie Charger {suffix}".rstrip(),
            serial_number=charger_id,
            sw_version=_format_sw_version(status.get("sw_ver")),
            hw_version=_format_fw_version(status.get("fw_ver")),
            configuration_url=f"http://{self.coordinator.client.host}",
        )
