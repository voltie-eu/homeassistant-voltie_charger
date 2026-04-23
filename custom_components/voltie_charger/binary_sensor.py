"""Binary sensor platform for Voltie Charger."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VoltieChargerConfigEntry
from .const import DATA_POWER, DATA_STATUS
from .entity import VoltieChargerEntity


@dataclass(frozen=True, kw_only=True)
class VoltieBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_STATUS, {}) or {}


def _power_stat(data: dict[str, Any]) -> dict[str, Any]:
    return (data.get(DATA_POWER, {}) or {}).get("power_stat", {}) or {}


BINARY_SENSORS: tuple[VoltieBinarySensorDescription, ...] = (
    VoltieBinarySensorDescription(
        key="car_connected",
        translation_key="car_connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda d: _status(d).get("is_car_connected"),
    ),
    VoltieBinarySensorDescription(
        key="is_charging",
        translation_key="is_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda d: _status(d).get("is_charging"),
    ),
    VoltieBinarySensorDescription(
        key="dlm_valid",
        translation_key="dlm_valid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _power_stat(d).get("dlm_valid"),
    ),
    VoltieBinarySensorDescription(
        key="ipm_valid",
        translation_key="ipm_valid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _power_stat(d).get("ipm_valid"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VoltieChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        VoltieChargerBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    )


class VoltieChargerBinarySensor(VoltieChargerEntity, BinarySensorEntity):
    entity_description: VoltieBinarySensorDescription

    def __init__(self, coordinator, description: VoltieBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self.entity_description.value_fn(self.coordinator.data or {})
        return bool(value) if value is not None else None
