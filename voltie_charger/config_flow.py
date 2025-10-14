# config_flow.py
"""Config flow for Voltie Charger integration."""
import logging
import voluptuous as vol

import aiohttp

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


async def test_connection(hass, host, username, password):
    """Test if we can connect to the charger with the given credentials."""
    auth = aiohttp.BasicAuth(username, password)

    async with aiohttp.ClientSession() as session:
        url = f"http://{host}/status"

        try:
            async with session.get(url, auth=auth, timeout=10) as response:
                response.raise_for_status()
        except aiohttp.ClientResponseError as exc:
            if exc.status == 401:
                raise InvalidAuth from exc
            raise CannotConnect from exc
        except aiohttp.ClientError as exc:
            raise CannotConnect from exc


class EVChargerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Voltie Charger."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                await test_connection(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Voltie Charger ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )