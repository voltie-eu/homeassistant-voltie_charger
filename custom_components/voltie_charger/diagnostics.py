"""Diagnostics for the Voltie Charger integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import VoltieChargerConfigEntry

REDACT_CONFIG = {CONF_PASSWORD, CONF_USERNAME, CONF_HOST}
REDACT_DATA = {"charger_id", "idtag", "idtag_name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VoltieChargerConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "data": async_redact_data(coordinator.data or {}, REDACT_DATA),
        },
    }
