# __init__.py
"""The Voltie Charger integration."""
import logging
import asyncio
from datetime import timedelta
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


class EVChargerCoordinator(DataUpdateCoordinator):
    """EV Charger data update coordinator."""

    def __init__(self, hass: HomeAssistant, host: str, username: str, password: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=5),
        )
        self._host = host
        self.auth = aiohttp.BasicAuth(username, password)
        self.session = aiohttp.ClientSession()

    async def _async_update_data(self) -> dict:
        """Fetch data from the charger."""
        async def fetch(endpoint: str):
            url = f"http://{self._host}/{endpoint}"
            try:
                async with self.session.get(url, auth=self.auth, timeout=10) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as exc:
                raise UpdateFailed(f"Error communicating with Voltie Charger ({endpoint}): {exc}") from exc

        status_data = await fetch("status")
        await asyncio.sleep(.2)  # small delay (200ms) before next fetch
        power_data = await fetch("power")

        return {
            "status": status_data,
            "power": power_data
        }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Voltie Charger from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = entry.data
    host = config["host"]
    username = config["username"]
    password = config["password"]

    coordinator = EVChargerCoordinator(hass, host, username, password)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["coordinator"].session.close()
    return unload_ok
