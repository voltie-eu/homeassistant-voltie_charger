"""Number platform for Voltie Charger — exposes the charging current limit."""
from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VoltieChargerConfigEntry, VoltieChargerCoordinator
from .client import (
    VoltieChargerAuthError,
    VoltieChargerConnectionError,
    VoltieChargerRejectedError,
)
from .const import (
    CURRENT_LIMIT_MAX,
    CURRENT_LIMIT_MIN,
    CURRENT_LIMIT_STEP,
    DATA_CONFIG,
)
from .entity import VoltieChargerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VoltieChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger number entities."""
    async_add_entities([VoltieChargerCurrentLimit(entry.runtime_data)])


class VoltieChargerCurrentLimit(VoltieChargerEntity, NumberEntity):
    """Writable charging current limit (6–32 A)."""

    _attr_translation_key = "current_limit"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = CURRENT_LIMIT_MIN
    _attr_native_max_value = CURRENT_LIMIT_MAX
    _attr_native_step = CURRENT_LIMIT_STEP

    def __init__(self, coordinator: VoltieChargerCoordinator) -> None:
        super().__init__(coordinator, "current_limit")

    @property
    def available(self) -> bool:
        """Only available if /config returned data (some firmware lacks it)."""
        if not super().available:
            return False
        config = (self.coordinator.data or {}).get(DATA_CONFIG) or {}
        return "conf_current_limit" in config

    @property
    def native_value(self) -> float | None:
        config = (self.coordinator.data or {}).get(DATA_CONFIG, {})
        value = config.get("conf_current_limit")
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.async_push_config(
                {"conf_current_limit": int(value)}
            )
        except VoltieChargerAuthError as exc:
            raise HomeAssistantError(f"Authentication failed: {exc}") from exc
        except VoltieChargerRejectedError as exc:
            raise HomeAssistantError(f"Charger rejected the change: {exc}") from exc
        except VoltieChargerConnectionError as exc:
            raise HomeAssistantError(f"Cannot reach charger: {exc}") from exc
