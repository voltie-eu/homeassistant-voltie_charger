"""Config and options flow for the Voltie Charger integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .client import (
    VoltieChargerAuthError,
    VoltieChargerClient,
    VoltieChargerConnectionError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_USERNAME, default=""): cv.string,
        vol.Optional(CONF_PASSWORD, default=""): cv.string,
    }
)


async def _validate(
    hass, data: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    """Probe the charger and return (charger_id, errors)."""
    username = (data.get(CONF_USERNAME) or "").strip()
    password = data.get(CONF_PASSWORD) or ""

    # Reject half-filled credentials — users otherwise silently get no-auth.
    if bool(username) != bool(password):
        return "", {"base": "incomplete_credentials"}

    session = async_get_clientsession(hass)
    client = VoltieChargerClient(
        session,
        data[CONF_HOST],
        username or None,
        password or None,
    )
    try:
        status = await client.async_get_status()
    except VoltieChargerAuthError:
        return "", {"base": "invalid_auth"}
    except VoltieChargerConnectionError:
        return "", {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating charger")
        return "", {"base": "unknown"}

    charger_id = status.get("charger_id")
    if not charger_id:
        return "", {"base": "unknown"}
    return charger_id, {}


class VoltieChargerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Voltie Charger."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._discovered_charger_id: str | None = None
        self._discovered_mdns_name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            charger_id, errors = await _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(charger_id)
                self._abort_if_unique_id_configured()
                self.context["title_placeholders"] = {
                    "name": f"Voltie Charger {charger_id[-4:].lower()}",
                }
                return self.async_create_entry(
                    title=f"Voltie Charger ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **user_input}
            charger_id, errors = await _validate(self.hass, data)
            if not errors:
                await self.async_set_unique_id(charger_id)
                self._abort_if_unique_id_mismatch(reason="wrong_charger")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=user_input,
                    reason="reauth_successful",
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                ): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"host": entry.data.get(CONF_HOST, "")},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow host / credentials to be changed in-place."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            charger_id, errors = await _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(charger_id)
                self._abort_if_unique_id_mismatch(reason="wrong_charger")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=user_input,
                )

        defaults = {**entry.data, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): cv.string,
                vol.Optional(
                    CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")
                ): cv.string,
                vol.Optional(
                    CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")
                ): cv.string,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a charger announcing itself over mDNS."""
        hostname = (discovery_info.hostname or "").rstrip(".")
        host = hostname or str(discovery_info.ip_address)
        if not host:
            return self.async_abort(reason="cannot_connect")

        mdns_name = (discovery_info.name or "").split(".", 1)[0].lower() or host
        self._discovered_host = host
        self._discovered_mdns_name = mdns_name

        charger_id, errors = await _validate(
            self.hass, {CONF_HOST: host, CONF_USERNAME: "", CONF_PASSWORD: ""}
        )

        if errors.get("base") == "invalid_auth":
            if host_abort := self._host_configured_abort(host):
                return host_abort
            await self.async_set_unique_id(f"mdns_{mdns_name}")
            self._abort_if_unique_id_configured()
            self.context["title_placeholders"] = {
                "name": f"Voltie Charger {mdns_name[-4:].lower()}"
            }
            return await self.async_step_discovery_auth()

        if errors:
            if host_abort := self._host_configured_abort(host):
                return host_abort
            await self.async_set_unique_id(f"mdns_{mdns_name}")
            self._abort_if_unique_id_configured()
            self.context["title_placeholders"] = {
                "name": f"Voltie Charger {mdns_name[-4:].lower()}"
            }
            return await self.async_step_api_disabled()

        await self.async_set_unique_id(charger_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host}, reload_on_update=True
        )

        self._discovered_charger_id = charger_id
        self.context["title_placeholders"] = {
            "name": f"Voltie Charger {charger_id[-4:].lower()}",
            "host": host,
        }
        return await self.async_step_zeroconf_confirm()

    def _host_configured_abort(self, host: str) -> ConfigFlowResult | None:
        """Return an abort result if an existing entry is already using this host."""
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_HOST) == host:
                return self.async_abort(reason="already_configured")
        return None

    async def async_step_api_disabled(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reachable on the LAN but the HTTP API is disabled."""
        assert self._discovered_host is not None

        if user_input is not None and user_input.get("next_step_id") == "api_retry":
            return await self.async_step_api_retry()

        return self.async_show_menu(
            step_id="api_disabled",
            menu_options=["api_retry"],
            description_placeholders={"host": self._discovered_host},
        )

    async def async_step_api_retry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-probe after the user has (hopefully) enabled the HTTP API."""
        assert self._discovered_host is not None
        assert self._discovered_mdns_name is not None

        charger_id, errors = await _validate(
            self.hass,
            {
                CONF_HOST: self._discovered_host,
                CONF_USERNAME: "",
                CONF_PASSWORD: "",
            },
        )

        if errors.get("base") == "invalid_auth":
            return await self.async_step_discovery_auth()
        if errors:
            return await self.async_step_api_disabled()

        await self.async_set_unique_id(charger_id, raise_on_progress=False)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: self._discovered_host},
            reload_on_update=True,
        )

        self._discovered_charger_id = charger_id
        self.context["title_placeholders"] = {
            "name": f"Voltie Charger {charger_id[-4:].lower()}",
            "host": self._discovered_host,
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm adding a discovered charger."""
        assert self._discovered_host is not None
        if user_input is not None:
            return self.async_create_entry(
                title=f"Voltie Charger ({self._discovered_host})",
                data={
                    CONF_HOST: self._discovered_host,
                    CONF_USERNAME: "",
                    CONF_PASSWORD: "",
                },
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"host": self._discovered_host},
        )

    async def async_step_discovery_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for credentials when the discovered charger requires auth."""
        assert self._discovered_host is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {CONF_HOST: self._discovered_host, **user_input}
            charger_id, errors = await _validate(self.hass, data)
            if not errors:
                await self.async_set_unique_id(charger_id, raise_on_progress=False)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: self._discovered_host},
                    reload_on_update=True,
                )
                return self.async_create_entry(
                    title=f"Voltie Charger ({self._discovered_host})",
                    data=data,
                )

        return self.async_show_form(
            step_id="discovery_auth",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                }
            ),
            description_placeholders={"host": self._discovered_host},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return VoltieChargerOptionsFlow()


class VoltieChargerOptionsFlow(OptionsFlow):
    """Options flow — currently just the poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
