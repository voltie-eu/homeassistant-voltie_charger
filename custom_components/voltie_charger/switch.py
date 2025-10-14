# switch.py
"""Switch platform for EV Charger REST API."""
import logging
import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
    """Set up the Voltie Charger switch."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities(
        [
            EVChargerSwitch(
                coordinator,
                entry.entry_id,
            )
        ]
    )

class EVChargerSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Voltie Charger Switch."""

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self._attr_name = f"Voltie Charger Switch {entry_id}"
        self._attr_unique_id = f"voltie_charger_switch_{entry_id}"

    @property
    def is_on(self) -> bool:
        """Return true if the charger is enabled."""
        return self.coordinator.data["status"].get("charge_enabled", False)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "Voltie Charger",
            "manufacturer": "Voltie",
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Send the start command to the charger."""
        _LOGGER.info("Turning on Voltie Charger at %s", self.coordinator._host)
        url = f"http://{self.coordinator._host}/start"

        try:
            async with self.coordinator.session.get(url, auth=self.coordinator.auth, timeout=10) as response:
                response.raise_for_status()
            await asyncio.sleep(3)  # Wait 3 seconds for charger to update state
            await self.coordinator.async_refresh()  # Force immediate refresh after delay
        except Exception as exc:
            _LOGGER.error("Error communicating with Voltie Charger: %s", exc)

    async def async_turn_off(self, **kwargs) -> None:
        """Send the stop command to the charger."""
        _LOGGER.info("Turning off Voltie Charger at %s", self.coordinator._host)
        url = f"http://{self.coordinator._host}/stop"

        try:
            async with self.coordinator.session.get(url, auth=self.coordinator.auth, timeout=10) as response:
                response.raise_for_status()
            await asyncio.sleep(3)  # Wait 3 seconds for charger to update state
            await self.coordinator.async_refresh()  # Force immediate refresh after delay
        except Exception as exc:
            _LOGGER.error("Error communicating with Voltie Charger: %s", exc)