# sensor.py
"""Sensor platform for Voltie Charger."""
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Log the coordinator data for debugging
    _LOGGER.debug("Coordinator data: %s", coordinator.data)

    entities = [
        # -- /status --
        ChargerIDSensor(coordinator, entry.entry_id),
        MainsVoltageSensor(coordinator, entry.entry_id),
        PhasesSensor(coordinator, entry.entry_id),
        CurrentOfferedSensor(coordinator, entry.entry_id),
        ChargeCurrentSensor(coordinator, entry.entry_id),
        ChargePowerSensor(coordinator, entry.entry_id),
        SessionEnergySensor(coordinator, entry.entry_id),
        SessionChargeTimeSensor(coordinator, entry.entry_id),
        SessionIdleTimeSensor(coordinator, entry.entry_id),
        AveragePowerSensor(coordinator, entry.entry_id),

        # -- /power --
        PowerVoltageSensor(coordinator, entry.entry_id, 1),
        PowerVoltageSensor(coordinator, entry.entry_id, 2),
        PowerVoltageSensor(coordinator, entry.entry_id, 3),
        PowerCurrentSensor(coordinator, entry.entry_id, 1),
        PowerCurrentSensor(coordinator, entry.entry_id, 2),
        PowerCurrentSensor(coordinator, entry.entry_id, 3),
        PowerPowerSensor(coordinator, entry.entry_id, 1),
        PowerPowerSensor(coordinator, entry.entry_id, 2),
        PowerPowerSensor(coordinator, entry.entry_id, 3),
        PowerDLMCurrentSensor(coordinator, entry.entry_id, 1),
        PowerDLMCurrentSensor(coordinator, entry.entry_id, 2),
        PowerDLMCurrentSensor(coordinator, entry.entry_id, 3),
        PowerIPMCurrentSensor(coordinator, entry.entry_id, 1),
        PowerIPMCurrentSensor(coordinator, entry.entry_id, 2),
        PowerIPMCurrentSensor(coordinator, entry.entry_id, 3),
    ]

    async_add_entities(entities)

class ChargerIDSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger ID {entry_id}"
        self._attr_unique_id = f"voltie_charger_id_{entry_id}"
        self._attr_icon = "mdi:identifier"

    @property
    def native_value(self):
        return self.coordinator.data["status"].get("charger_id")
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }
    

class MainsVoltageSensor(CoordinatorEntity, SensorEntity):
    """Representation of mains voltage sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Mains Voltage {entry_id}"
        self._attr_unique_id = f"voltie_charger_mains_voltage_{entry_id}"
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        value = self.coordinator.data["status"].get("mains_voltage")
        _LOGGER.debug("Mains Voltage (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class PhasesSensor(CoordinatorEntity, SensorEntity):
    """Representation of phases sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Phases {entry_id}"
        self._attr_unique_id = f"voltie_charger_phases_{entry_id}"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        value = self.coordinator.data["status"].get("phases")
        _LOGGER.debug("Phases (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class CurrentOfferedSensor(CoordinatorEntity, SensorEntity):
    """Representation of current offered sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Current Offered {entry_id}"
        self._attr_unique_id = f"voltie_charger_current_offered_{entry_id}"
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        value = self.coordinator.data["status"].get("current_offered")
        _LOGGER.debug("Current Offered (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class ChargeCurrentSensor(CoordinatorEntity, SensorEntity):
    """Representation of charge current sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Charge Current {entry_id}"
        self._attr_unique_id = f"voltie_charger_charge_current_{entry_id}"
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        value = self.coordinator.data["status"].get("charge_current")
        _LOGGER.debug("Charge Current (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class ChargePowerSensor(CoordinatorEntity, SensorEntity):
    """Representation of charge power sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Charge Power {entry_id}"
        self._attr_unique_id = f"voltie_charger_charge_power_{entry_id}"
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        value = self.coordinator.data["status"].get("charge_power")
        _LOGGER.debug("Charge Power (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class SessionEnergySensor(CoordinatorEntity, SensorEntity):
    """Representation of session energy sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Session Energy {entry_id}"
        self._attr_unique_id = f"voltie_charger_session_energy_{entry_id}"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self):
        """Return the value of the sensor."""
        cdr = self.coordinator.data["status"].get("cdr", {})
        value = cdr.get("chg_energy")
        _LOGGER.debug("Session Energy (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class SessionChargeTimeSensor(CoordinatorEntity, SensorEntity):
    """Representation of session charge time sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Session Charge Time {entry_id}"
        self._attr_unique_id = f"voltie_charger_session_charge_time_{entry_id}"
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        cdr = self.coordinator.data["status"].get("cdr", {})
        value = cdr.get("chg_time")
        _LOGGER.debug("Session Charge Time (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class SessionIdleTimeSensor(CoordinatorEntity, SensorEntity):
    """Representation of session idle time sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Session Idle Time {entry_id}"
        self._attr_unique_id = f"voltie_charger_session_idle_time_{entry_id}"
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        cdr = self.coordinator.data["status"].get("cdr", {})
        value = cdr.get("idle_time")
        _LOGGER.debug("Session Idle Time (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class AveragePowerSensor(CoordinatorEntity, SensorEntity):
    """Representation of average power sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Average Power {entry_id}"
        self._attr_unique_id = f"voltie_charger_average_power_{entry_id}"
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the value of the sensor."""
        cdr = self.coordinator.data["status"].get("cdr", {})
        value = cdr.get("avg_power")
        _LOGGER.debug("Average Power (%s): %s", self._attr_unique_id, value)
        return value

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class PowerVoltageSensor(CoordinatorEntity, SensorEntity):
    """Representation of per-phase voltage sensor."""

    def __init__(self, coordinator, entry_id: str, phase: int) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.phase = phase
        self._attr_name = f"Voltie Charger Voltage L{phase} {entry_id}"
        self._attr_unique_id = f"voltie_charger_voltage_l{phase}_{entry_id}"
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data.get("power", {}).get("power_stat", {})
        value = data.get(f"voltage{self.phase}")
        _LOGGER.debug("Voltage L%s (%s): %s", self.phase, self._attr_unique_id, value)
        return value
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }


class PowerCurrentSensor(CoordinatorEntity, SensorEntity):
    """Representation of per-phase current sensor."""

    def __init__(self, coordinator, entry_id: str, phase: int) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.phase = phase
        self._attr_name = f"Voltie Charger Current L{phase} {entry_id}"
        self._attr_unique_id = f"voltie_charger_current_l{phase}_{entry_id}"
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data.get("power", {}).get("power_stat", {})
        value = data.get(f"current{self.phase}")
        _LOGGER.debug("Current L%s (%s): %s", self.phase, self._attr_unique_id, value)
        return value
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }


class PowerPowerSensor(CoordinatorEntity, SensorEntity):
    """Representation of per-phase power sensor."""

    def __init__(self, coordinator, entry_id: str, phase: int) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.phase = phase
        self._attr_name = f"Voltie Charger Power L{phase} {entry_id}"
        self._attr_unique_id = f"voltie_charger_power_l{phase}_{entry_id}"
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data.get("power", {}).get("power_stat", {})
        value = data.get(f"power{self.phase}")
        _LOGGER.debug("Power L%s (%s): %s", self.phase, self._attr_unique_id, value)
        return value
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }
    
class PowerDLMCurrentSensor(CoordinatorEntity, SensorEntity):
    """Representation of per-phase dlm current sensor."""

    def __init__(self, coordinator, entry_id: str, phase: int) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.phase = phase
        self._attr_name = f"Voltie Charger DLM Current L{phase} {entry_id}"
        self._attr_unique_id = f"voltie_charger_dlm_current_l{phase}_{entry_id}"
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data.get("power", {}).get("power_stat", {})
        value = data.get(f"dlm_current{self.phase}")
        _LOGGER.debug("DLM Current L%s (%s): %s", self.phase, self._attr_unique_id, value)
        return value
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }
    
class PowerIPMCurrentSensor(CoordinatorEntity, SensorEntity):
    """Representation of per-phase ipm current sensor."""

    def __init__(self, coordinator, entry_id: str, phase: int) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.phase = phase
        self._attr_name = f"Voltie Charger IPM Current L{phase} {entry_id}"
        self._attr_unique_id = f"voltie_charger_ipm_current_l{phase}_{entry_id}"
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data.get("power", {}).get("power_stat", {})
        value = data.get(f"ipm_current{self.phase}")
        _LOGGER.debug("DLM Current L%s (%s): %s", self.phase, self._attr_unique_id, value)
        return value
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }