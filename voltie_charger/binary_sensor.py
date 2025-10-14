# binary_sensor.py
"""Binary sensor platform for Voltie Charger."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        # -- /status --
        CarConnectedBinarySensor(coordinator, entry.entry_id),
        IsChargingBinarySensor(coordinator, entry.entry_id),
        AutostartBinarySensor(coordinator, entry.entry_id),

        # -- /power --
        DLMValidBinarySensor(coordinator, entry.entry_id),
        IPMValidBinarySensor(coordinator, entry.entry_id),
    ]

    async_add_entities(entities)

class CarConnectedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of car connected binary sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Car Connected {entry_id}"
        self._attr_unique_id = f"voltie_charger_car_connected_{entry_id}"
        self._attr_device_class = BinarySensorDeviceClass.PLUG

    @property
    def is_on(self) -> bool:
        """Return true if car is connected."""
        return self.coordinator.data["status"].get("is_car_connected", False)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class IsChargingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of is charging binary sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Is Charging {entry_id}"
        self._attr_unique_id = f"voltie_charger_is_charging_{entry_id}"
        self._attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def is_on(self) -> bool:
        """Return true if charging."""
        return self.coordinator.data["status"].get("is_charging", False)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

class AutostartBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of autostart binary sensor."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Autostart {entry_id}"
        self._attr_unique_id = f"voltie_charger_autostart_{entry_id}"

    @property
    def is_on(self) -> bool:
        """Return true if autostart is enabled."""
        return self.coordinator.data["status"].get("autostart", False)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }
    
class DLMValidBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for DLM validity."""

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger DLM Valid {entry_id}"
        self._attr_unique_id = f"voltie_charger_dlm_valid_{entry_id}"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data.get("power", {}).get("power_stat", {})
        return data.get("dlm_valid", False)
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }


class IPMValidBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for IPM validity."""

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger IPM Valid {entry_id}"
        self._attr_unique_id = f"voltie_charger_ipm_valid_{entry_id}"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data.get("power", {}).get("power_stat", {})
        return data.get("ipm_valid", False)
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }