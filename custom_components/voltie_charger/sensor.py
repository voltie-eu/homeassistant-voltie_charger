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

from . import VoltieChargerConfigEntry, VoltieChargerCoordinator
from .const import (
    DATA_POWER,
    DATA_RFID_STATUS,
    DATA_STATUS,
    EVSE_STATE_ERROR,
    EVSE_STATES,
)
from .entity import VoltieChargerEntity, VoltieChargerRfidEntity


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
    stat = (data.get(DATA_POWER) or {}).get("power_stat")
    return stat if isinstance(stat, dict) else {}


def _rfid(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(DATA_RFID_STATUS, {}) or {}


def _numeric(value: Any) -> int | float | None:
    """Return the value only if HA can put it in a numeric state.

    Anything else — a string, a dict, or a bool, which is an int in Python but
    renders as "True" — would raise inside SensorEntity.state on a sensor with a
    device_class or state_class. That exception propagates out of the
    coordinator's listener dispatch and stops every entity after it updating, so
    one bad field would freeze half the device.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _phases_value(data: dict[str, Any]) -> str | None:
    value = _status(data).get("phases")
    # Compared as an int, not by membership: `3.0 in (1, 3)` and `True in (1, 3)`
    # are both true, and str() would then yield "3.0"/"True", which are not in
    # this ENUM's options.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != int(value) or int(value) not in (1, 3):
        return None
    return str(int(value))


def _evse_state(data: dict[str, Any]) -> str:
    # Missing field → unknown (not error); avoids false-positive fault UI.
    raw = _status(data).get("evse_state")
    if raw is None:
        return EVSE_STATES[0]
    if isinstance(raw, bool) or not isinstance(raw, int):
        # An unhashable or non-integer code would raise in dict.get().
        return EVSE_STATE_ERROR
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
        key="phases_used",
        translation_key="phases_used",
        # Phases in the *current session* (0 when idle). Kept a plain numeric
        # sensor rather than an enum like "phases": the spec does not enumerate
        # the possible values, and an ENUM sensor logs an error for anything
        # outside options. No state_class — averaging a 0/1/3 phase count over
        # an hour is not a meaningful statistic.
        value_fn=lambda d: _numeric(_status(d).get("phases_used")),
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
        key="current_hw_limit",
        translation_key="current_hw_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        # A fixed hardware capability rather than a live reading: diagnostic,
        # and no state_class, since recording hourly statistics for a constant
        # only costs database space.
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda d: _numeric(_status(d).get("current_hw_limit")),
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


RFID_SENSORS: tuple[VoltieSensorDescription, ...] = (
    VoltieSensorDescription(
        key="rfid_list_count",
        translation_key="rfid_list_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _numeric(_rfid(d).get("list_count")),
    ),
    VoltieSensorDescription(
        key="rfid_list_capacity",
        translation_key="rfid_list_capacity",
        # Constant for a given firmware, so no state_class.
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _numeric(_rfid(d).get("list_capacity")),
    ),
    VoltieSensorDescription(
        key="rfid_learn_remaining",
        translation_key="rfid_learn_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _numeric(_rfid(d).get("learn_to_sec")),
    ),
    VoltieSensorDescription(
        key="rfid_list_format_ver",
        translation_key="rfid_list_format_ver",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _numeric(_rfid(d).get("list_format_ver")),
    ),
    VoltieSensorDescription(
        key="rfid_list_hash",
        translation_key="rfid_list_hash",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # 8 hex digits, not a number — a device_class or state_class here would
        # make the recorder try to coerce it.
        value_fn=lambda d: _rfid(d).get("list_hash"),
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
    entities: list[SensorEntity] = [
        VoltieChargerSensor(coordinator, description)
        for description in (*SENSORS, *PER_PHASE_SENSORS)
    ]
    entities.append(VoltieChargerApiVersionSensor(coordinator))
    # Skipped entirely on pre-v5 firmware so old chargers don't get a row of
    # permanently unavailable entities.
    if coordinator.rfid_supported:
        entities.extend(
            VoltieChargerRfidSensor(coordinator, description)
            for description in RFID_SENSORS
        )
    async_add_entities(entities)


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


class VoltieChargerRfidSensor(VoltieChargerRfidEntity, SensorEntity):
    """A sensor backed by /rfid/status, which only exists on API v5 firmware."""

    entity_description: VoltieSensorDescription

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
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


class VoltieChargerApiVersionSensor(VoltieChargerEntity, SensorEntity):
    """The charger's major API version.

    Needs its own class rather than a description: /apiver is probed once during
    setup and lives on the coordinator, not in its polled data.
    """

    _attr_translation_key = "api_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VoltieChargerCoordinator) -> None:
        super().__init__(coordinator, "api_version")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.api_version
