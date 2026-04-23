"""HTTP client for the Voltie Charger API."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from .const import (
    API_PORT,
    ENDPOINT_CONFIG,
    ENDPOINT_POWER,
    ENDPOINT_START,
    ENDPOINT_STATUS,
    ENDPOINT_STOP,
    HA_START_NAME,
    REQUEST_TIMEOUT,
)


class VoltieChargerError(Exception):
    """Base exception for the Voltie Charger client."""


class VoltieChargerAuthError(VoltieChargerError):
    """Raised when authentication is rejected."""


class VoltieChargerConnectionError(VoltieChargerError):
    """Raised when the charger is unreachable or returns an unusable response."""


class VoltieChargerRejectedError(VoltieChargerError):
    """Raised when the charger rejects a request (bad parameters, unsupported)."""


# API error codes (spec v4.4). 0 = OK.
_API_ERROR_MESSAGES: dict[int, str] = {
    1: "internal error",
    5: "incorrect message format or parameter",
}


class VoltieChargerClient:
    """Thin wrapper around the charger's HTTP API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._session = session
        self._host = host
        self._auth = (
            aiohttp.BasicAuth(username, password)
            if username and password
            else None
        )

    @property
    def host(self) -> str:
        return self._host

    def _url(self, endpoint: str) -> str:
        return f"http://{self._host}:{API_PORT}/{endpoint}"

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(endpoint)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        try:
            async with self._session.request(
                method,
                url,
                auth=self._auth,
                params=params,
                json=json_body,
                timeout=timeout,
            ) as response:
                if response.status == 401:
                    raise VoltieChargerAuthError(
                        "Authentication rejected by charger"
                    )
                response.raise_for_status()
                raw = await response.read()
        except VoltieChargerError:
            raise
        except aiohttp.ClientResponseError as exc:
            if exc.status == 401:
                raise VoltieChargerAuthError(str(exc)) from exc
            raise VoltieChargerConnectionError(
                f"HTTP {exc.status} from {endpoint}: {exc.message}"
            ) from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise VoltieChargerConnectionError(
                f"Error talking to charger ({endpoint}): {exc}"
            ) from exc

        try:
            payload = json.loads(raw) if raw else {}
        except (ValueError, json.JSONDecodeError) as exc:
            raise VoltieChargerConnectionError(
                f"Non-JSON response from {endpoint}: {raw[:200]!r}"
            ) from exc

        if not isinstance(payload, dict):
            raise VoltieChargerConnectionError(
                f"Unexpected response shape from {endpoint}: {type(payload).__name__}"
            )

        # Some failure responses carry a textual "status" field instead of
        # error_code — surface those as transient connection issues so the
        # coordinator retries instead of treating them as auth failures.
        if (internal := payload.get("status")) and isinstance(internal, str):
            raise VoltieChargerConnectionError(
                f"Charger reported internal condition ({endpoint}): {internal}"
            )

        if (code := payload.get("error_code")) not in (None, 0):
            message = _API_ERROR_MESSAGES.get(int(code), f"error_code={code}")
            raise VoltieChargerRejectedError(
                f"Charger rejected {method} {endpoint}: {message}"
            )

        return payload

    async def async_get_status(self) -> dict[str, Any]:
        return await self._request("GET", ENDPOINT_STATUS)

    async def async_get_power(self) -> dict[str, Any]:
        return await self._request("GET", ENDPOINT_POWER)

    async def async_get_config(self) -> dict[str, Any]:
        return await self._request("GET", ENDPOINT_CONFIG)

    async def async_set_config(self, values: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("PUT", ENDPOINT_CONFIG, json_body=values)
        # The charger reports how many parameters it accepted. A shortfall
        # means the hardware silently rejected one and we need to tell the
        # caller — otherwise the UI would flip optimistically without effect.
        accepted = result.get("accepted")
        if isinstance(accepted, int) and accepted < len(values):
            raise VoltieChargerRejectedError(
                f"Charger accepted only {accepted}/{len(values)} config "
                "parameters; the rest were rejected (unsupported on this "
                "hardware, cable connected, or EVSE in an error state)."
            )
        return result

    async def async_start(
        self,
        *,
        id_tag: str | None = None,
        name: str | None = HA_START_NAME,
    ) -> dict[str, Any]:
        params: dict[str, str] = {}
        if id_tag:
            params["id_tag"] = id_tag
        if name:
            params["name"] = name
        return await self._request("GET", ENDPOINT_START, params=params or None)

    async def async_stop(self) -> dict[str, Any]:
        return await self._request("GET", ENDPOINT_STOP)
