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

from . import VoltieChargerConfigEntry, VoltieChargerCoordinator
from .const import (
    DATA_POWER,
    DATA_RFID_STATUS,
    DATA_STATUS,
    EVSE_NON_PROBLEM_STATES,
    EVSE_STATE_ERROR,
    EVSE_STATES,
)
from .entity import VoltieChargerEntity, VoltieChargerRfidEntity


@dataclass(frozen=True, kw_only=True)
class VoltieBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_STATUS, {}) or {}


def _power_stat(data: dict[str, Any]) -> dict[str, Any]:
    stat = (data.get(DATA_POWER) or {}).get("power_stat")
    return stat if isinstance(stat, dict) else {}


def _rfid_status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_RFID_STATUS, {}) or {}


def _evse_code(data: dict[str, Any]) -> int | None:
    raw = _status(data).get("evse_state")
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _problem(data: dict[str, Any]) -> bool | None:
    # A missing or malformed state is unknown rather than an alarm.
    if (code := _evse_code(data)) is None:
        return None
    return code not in EVSE_NON_PROBLEM_STATES


def _problem_attributes(data: dict[str, Any]) -> dict[str, Any]:
    code = _evse_code(data)
    return {
        # The evse_state option, so it shares that sensor's translations.
        "error": (
            EVSE_STATES.get(code, EVSE_STATE_ERROR)
            if code is not None and code not in EVSE_NON_PROBLEM_STATES
            else None
        ),
        "raw_code": code,
    }


BINARY_SENSORS: tuple[VoltieBinarySensorDescription, ...] = (
    # The one entity to automate on for faults; evse_state has the detail but
    # needs a condition per code.
    VoltieBinarySensorDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_problem,
        attributes_fn=_problem_attributes,
    ),
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

RFID_BINARY_SENSORS: tuple[VoltieBinarySensorDescription, ...] = (
    VoltieBinarySensorDescription(
        key="rfid_reader_enabled",
        translation_key="rfid_reader_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _rfid_status(d).get("reader_enabled"),
    ),
    VoltieBinarySensorDescription(
        key="rfid_reader_working",
        translation_key="rfid_reader_working",
        entity_category=EntityCategory.DIAGNOSTIC,
        # No CONNECTIVITY device class: it renders as "Connected/Disconnected",
        # which misdescribes a reader that is present but out of service.
        value_fn=lambda d: _rfid_status(d).get("reader_working"),
    ),
    VoltieBinarySensorDescription(
        key="rfid_learn_in_progress",
        translation_key="rfid_learn_in_progress",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _rfid_status(d).get("learn_in_progress"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VoltieChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        VoltieChargerBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    ]
    if coordinator.rfid_supported:
        entities.extend(
            VoltieChargerRfidBinarySensor(coordinator, desc)
            for desc in RFID_BINARY_SENSORS
        )
    async_add_entities(entities)


class VoltieChargerBinarySensor(VoltieChargerEntity, BinarySensorEntity):
    entity_description: VoltieBinarySensorDescription

    def __init__(self, coordinator, description: VoltieBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self.entity_description.value_fn(self.coordinator.data or {})
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attributes_fn
        if fn is None:
            return None
        return fn(self.coordinator.data or {})


class VoltieChargerRfidBinarySensor(VoltieChargerRfidEntity, BinarySensorEntity):
    """RFID reader diagnostic backed by /rfid/status."""

    entity_description: VoltieBinarySensorDescription

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
        description: VoltieBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self.entity_description.value_fn(self.coordinator.data or {})
        return bool(value) if value is not None else None
