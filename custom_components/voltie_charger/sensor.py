"""Sensor platform for Voltie Charger."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VoltieChargerConfigEntry
from .const import DATA_POWER, DATA_STATUS, EVSE_STATE_ERROR, EVSE_STATES
from .entity import VoltieChargerEntity


@dataclass(frozen=True, kw_only=True)
class VoltieSensorDescription(SensorEntityDescription):
    """Sensor description with a value accessor and optional attributes."""

    value_fn: Callable[[dict[str, Any]], Any]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_STATUS, {}) or {}


def _cdr(data: dict[str, Any]) -> dict[str, Any]:
    cdr = _status(data).get("cdr")
    return cdr if isinstance(cdr, dict) else {}


def _power_stat(data: dict[str, Any]) -> dict[str, Any]:
    return (data.get(DATA_POWER, {}) or {}).get("power_stat", {}) or {}


def _phases_value(data: dict[str, Any]) -> str | None:
    value = _status(data).get("phases")
    return str(value) if value in (1, 3) else None


def _evse_state(data: dict[str, Any]) -> str:
    # Missing field → unknown (not error); avoids false-positive fault UI.
    raw = _status(data).get("evse_state")
    if raw is None:
        return EVSE_STATES[0]
    return EVSE_STATES.get(raw, EVSE_STATE_ERROR)


SENSORS: tuple[VoltieSensorDescription, ...] = (
    VoltieSensorDescription(
        key="mains_voltage",
        translation_key="mains_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: _status(d).get("mains_voltage"),
    ),
    VoltieSensorDescription(
        key="phases",
        translation_key="phases",
        device_class=SensorDeviceClass.ENUM,
        options=["1", "3"],
        value_fn=_phases_value,
    ),
    VoltieSensorDescription(
        key="current_offered",
        translation_key="current_offered",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _status(d).get("current_offered"),
    ),
    VoltieSensorDescription(
        key="charge_current",
        translation_key="charge_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _status(d).get("charge_current"),
    ),
    VoltieSensorDescription(
        key="charge_power",
        translation_key="charge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _status(d).get("charge_power"),
    ),
    VoltieSensorDescription(
        key="evse_state",
        translation_key="evse_state",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[*EVSE_STATES.values(), EVSE_STATE_ERROR],
        value_fn=_evse_state,
        attributes_fn=lambda d: {"raw_code": _status(d).get("evse_state")},
    ),
    VoltieSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        value_fn=lambda d: _cdr(d).get("chg_energy"),
        # CDR metadata surfaced for UI cards rendering the per-period breakdown.
        attributes_fn=lambda d: {
            "session_start": _cdr(d).get("s_start"),
            "periods": _cdr(d).get("periods"),
        },
    ),
    VoltieSensorDescription(
        key="session_charge_time",
        translation_key="session_charge_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        # Per-session value, so MEASUREMENT — long-term stats get per-session mean/max.
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _cdr(d).get("chg_time"),
    ),
    VoltieSensorDescription(
        key="session_idle_time",
        translation_key="session_idle_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _cdr(d).get("idle_time"),
    ),
    VoltieSensorDescription(
        key="average_power",
        translation_key="average_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _cdr(d).get("avg_power"),
    ),
)


def _per_phase_sensors() -> tuple[VoltieSensorDescription, ...]:
    descriptions: list[VoltieSensorDescription] = []
    for phase in (1, 2, 3):
        descriptions.extend(
            (
                VoltieSensorDescription(
                    key=f"voltage_l{phase}",
                    translation_key="voltage_phase",
                    translation_placeholders={"phase": str(phase)},
                    device_class=SensorDeviceClass.VOLTAGE,
                    native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                    state_class=SensorStateClass.MEASUREMENT,
                    suggested_display_precision=1,
                    value_fn=lambda d, p=phase: _power_stat(d).get(f"voltage{p}"),
                ),
                VoltieSensorDescription(
                    key=f"current_l{phase}",
                    translation_key="current_phase",
                    translation_placeholders={"phase": str(phase)},
                    device_class=SensorDeviceClass.CURRENT,
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    state_class=SensorStateClass.MEASUREMENT,
                    suggested_display_precision=2,
                    value_fn=lambda d, p=phase: _power_stat(d).get(f"current{p}"),
                ),
                VoltieSensorDescription(
                    key=f"power_l{phase}",
                    translation_key="power_phase",
                    translation_placeholders={"phase": str(phase)},
                    device_class=SensorDeviceClass.POWER,
                    native_unit_of_measurement=UnitOfPower.KILO_WATT,
                    state_class=SensorStateClass.MEASUREMENT,
                    suggested_display_precision=2,
                    value_fn=lambda d, p=phase: _power_stat(d).get(f"power{p}"),
                ),
                VoltieSensorDescription(
                    key=f"dlm_current_l{phase}",
                    translation_key="dlm_current_phase",
                    translation_placeholders={"phase": str(phase)},
                    device_class=SensorDeviceClass.CURRENT,
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    state_class=SensorStateClass.MEASUREMENT,
                    entity_category=EntityCategory.DIAGNOSTIC,
                    entity_registry_enabled_default=False,
                    suggested_display_precision=2,
                    value_fn=lambda d, p=phase: _power_stat(d).get(f"dlm_current{p}"),
                ),
                VoltieSensorDescription(
                    key=f"ipm_current_l{phase}",
                    translation_key="ipm_current_phase",
                    translation_placeholders={"phase": str(phase)},
                    device_class=SensorDeviceClass.CURRENT,
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    state_class=SensorStateClass.MEASUREMENT,
                    entity_category=EntityCategory.DIAGNOSTIC,
                    entity_registry_enabled_default=False,
                    suggested_display_precision=2,
                    value_fn=lambda d, p=phase: _power_stat(d).get(f"ipm_current{p}"),
                ),
            )
        )
    return tuple(descriptions)


PER_PHASE_SENSORS = _per_phase_sensors()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VoltieChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        VoltieChargerSensor(coordinator, description)
        for description in (*SENSORS, *PER_PHASE_SENSORS)
    )


class VoltieChargerSensor(VoltieChargerEntity, SensorEntity):
    """A Voltie Charger sensor driven by a description."""

    entity_description: VoltieSensorDescription

    def __init__(
        self,
        coordinator,
        description: VoltieSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attributes_fn
        if fn is None:
            return None
        return fn(self.coordinator.data or {})
