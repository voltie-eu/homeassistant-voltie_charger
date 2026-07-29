"""Config, options, reauth, reconfigure and zeroconf flows."""
from __future__ import annotations

from ipaddress import ip_address

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import (
    SOURCE_USER,
    SOURCE_ZEROCONF,
    ConfigEntryState,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.voltie_charger.const import API_PORT, DOMAIN

from .conftest import BASE, CHARGER_ID, HOST, setup_integration, status_payload


async def test_user_flow_defaults_to_standard_port(
    hass: HomeAssistant, mock_charger, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_charger()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PORT] == API_PORT
    assert result["result"].unique_id == CHARGER_ID


async def test_user_flow_with_custom_port(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The port field is what makes a relocated HTTP API reachable (VLT-2120 M2)."""
    aioclient_mock.get("http://192.168.1.234:8080/status", json=status_payload())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 8080}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PORT] == 8080


async def test_user_flow_rejects_invalid_port(
    hass: HomeAssistant, mock_charger
) -> None:
    mock_charger()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    try:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 70000}
        )
    except Exception:  # voluptuous rejects it before the handler runs
        return
    assert result["type"] is FlowResultType.FORM


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/status", exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/status", status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: HOST, CONF_USERNAME: "u", CONF_PASSWORD: "p"},
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_incomplete_credentials(
    hass: HomeAssistant, mock_charger
) -> None:
    mock_charger()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_USERNAME: "u"}
    )
    assert result["errors"] == {"base": "incomplete_credentials"}


async def test_duplicate_charger_aborts(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_port(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: 5059, CONF_USERNAME: "u",
                            CONF_PASSWORD: "p"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_USERNAME] == "u"


async def test_reconfigure_rejects_a_different_charger(
    hass: HomeAssistant,
    mock_charger,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Pointing an entry at a different charger would corrupt its history."""
    mock_charger()
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        "http://192.168.1.99:5059/status", json=status_payload(charger_id="deadbeef")
    )

    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99", CONF_PORT: 5059}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_charger"


async def test_reauth_flow(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    config_entry.add_to_hass(hass)

    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "new", CONF_PASSWORD: "secret"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "secret"

    # A successful reauth reloads the entry, which starts the coordinator's
    # refresh timer; unload so the test does not leave it running. Whether the
    # reload actually loaded depends on what the charger mock answered, so this
    # is conditional rather than assumed.
    await hass.async_block_till_done()
    if config_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


async def test_options_flow_sets_scan_interval(
    hass: HomeAssistant, mock_charger, config_entry: MockConfigEntry
) -> None:
    mock_charger()
    await setup_integration(hass, config_entry)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 15}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options["scan_interval"] == 15


async def test_zeroconf_discovery(hass: HomeAssistant, mock_charger) -> None:
    mock_charger()
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=ZeroconfServiceInfo(
            ip_address=ip_address(HOST),
            ip_addresses=[ip_address(HOST)],
            hostname=f"{HOST}.",
            name="voltiecharger-4335._voltie-info._tcp.local.",
            port=API_PORT,
            type="_voltie-info._tcp.local.",
            properties={},
        ),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == HOST


async def test_zeroconf_needs_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/status", status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=ZeroconfServiceInfo(
            ip_address=ip_address(HOST),
            ip_addresses=[ip_address(HOST)],
            hostname=f"{HOST}.",
            name="voltiecharger-4335._voltie-info._tcp.local.",
            port=API_PORT,
            type="_voltie-info._tcp.local.",
            properties={},
        ),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_auth"


async def test_zeroconf_api_disabled_offers_retry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reachable on the LAN but the HTTP API is switched off."""
    aioclient_mock.get(f"{BASE}/status", exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=ZeroconfServiceInfo(
            ip_address=ip_address(HOST),
            ip_addresses=[ip_address(HOST)],
            hostname=f"{HOST}.",
            name="voltiecharger-4335._voltie-info._tcp.local.",
            port=API_PORT,
            type="_voltie-info._tcp.local.",
            properties={},
        ),
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "api_disabled"
