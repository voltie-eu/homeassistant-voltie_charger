"""HTTP client for the Voltie Charger API."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from .const import (
    API_PORT,
    CMD_CHARGER_REBOOT,
    CMD_DISPLAY_SCROLL_TEXT,
    CMD_REAR_LED_SET,
    CMD_RFID_LEARN,
    CMD_RFID_LEARN_CANCEL,
    ENDPOINT_APIVER,
    ENDPOINT_CONFIG,
    ENDPOINT_EXTRAS,
    ENDPOINT_POWER,
    ENDPOINT_RFID,
    ENDPOINT_RFID_EXTRAS,
    ENDPOINT_RFID_STATUS,
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


class VoltieChargerUnsupportedError(VoltieChargerRejectedError):
    """Raised when the firmware does not implement an endpoint or command.

    Subclasses the rejected error so existing handlers keep working, but lets
    callers recognise "your firmware is too old" and skip pointless retries.
    """


# API error codes (spec v5.0 section 3). 0 = OK.
_API_ERROR_MESSAGES: dict[int, str] = {
    1: "general error (e.g. command not possible in the current state)",
    5: "incorrect message format or parameter",
    23: (
        "not master: this charger is a secondary unit in a prepaid-RFID "
        "cluster, so send the command to the master unit instead"
    ),
    24: "unknown command (not supported by this firmware)",
}

# Only code 24 means "this firmware cannot do that". Code 23 is a cluster
# topology problem on perfectly current firmware, so it must not be reported as
# an out-of-date firmware — the remedy is a different target, not an update.
_UNSUPPORTED_ERROR_CODES = frozenset({24})


class VoltieChargerClient:
    """Thin wrapper around the charger's HTTP API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str | None = None,
        password: str | None = None,
        port: int = API_PORT,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._auth = (
            aiohttp.BasicAuth(username, password)
            if username and password
            else None
        )

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def _url(self, endpoint: str) -> str:
        return f"http://{self._host}:{self._port}/{endpoint}"

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
            if exc.status in (401, 403):
                raise VoltieChargerAuthError(str(exc)) from exc
            # 404/405 mean the endpoint isn't implemented — older firmware
            # rather than a network problem (spec section 3).
            if exc.status in (404, 405):
                raise VoltieChargerUnsupportedError(
                    f"{endpoint} is not available on this firmware "
                    f"(HTTP {exc.status})"
                ) from exc
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

        if (raw_code := payload.get("error_code")) is not None:
            # Coerced rather than compared directly: a charger that answers "0"
            # means success, and one that answers junk must raise a Voltie error
            # the coordinator can retry, not a bare ValueError that escapes the
            # whole exception hierarchy.
            if isinstance(raw_code, bool):
                code = None
            else:
                try:
                    code = int(raw_code)
                except (TypeError, ValueError):
                    code = None
            if code is None:
                raise VoltieChargerConnectionError(
                    f"Non-numeric error_code from {endpoint}: {raw_code!r}"
                )
            if code != 0:
                message = _API_ERROR_MESSAGES.get(code, f"error_code={code}")
                detail = f"Charger rejected {method} {endpoint}: {message}"
                if code in _UNSUPPORTED_ERROR_CODES:
                    raise VoltieChargerUnsupportedError(detail)
                raise VoltieChargerRejectedError(detail)

        # Some failure responses carry a textual "status" field instead of
        # error_code — surface those as transient connection issues so the
        # coordinator retries instead of treating them as auth failures.
        # Only trusted when no error_code came back at all: a normal payload
        # that ever grows a "status" key must not fail every poll.
        if payload.get("error_code") is None and isinstance(
            (internal := payload.get("status")), str
        ) and internal:
            raise VoltieChargerConnectionError(
                f"Charger reported internal condition ({endpoint}): {internal}"
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

    async def async_get_apiver(self) -> int | None:
        """Return the charger's major API version, or None if unreported."""
        payload = await self._request("GET", ENDPOINT_APIVER)
        value = payload.get("api_files_version")
        return int(value) if isinstance(value, (int, float)) else None

    # ---- /extras (spec 4.10) ----

    async def _async_command(
        self,
        endpoint: str,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"command": command}
        if params:
            body["params"] = params
        return await self._request("POST", endpoint, json_body=body)

    async def async_display_scroll_text(
        self,
        message: str,
        *,
        repeat_count: int | None = None,
        clear_first: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"message": message}
        if repeat_count is not None:
            params["repeat_count"] = repeat_count
        if clear_first is not None:
            params["clear_first"] = clear_first
        return await self._async_command(
            ENDPOINT_EXTRAS, CMD_DISPLAY_SCROLL_TEXT, params
        )

    async def async_set_rear_led(
        self,
        *,
        brightness: float,
        color_rgb: str,
        duration_sec: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "brightness": brightness,
            "color_rgb": color_rgb,
        }
        if duration_sec is not None:
            params["duration_sec"] = duration_sec
        return await self._async_command(
            ENDPOINT_EXTRAS, CMD_REAR_LED_SET, params
        )

    async def async_reboot(self) -> dict[str, Any]:
        return await self._async_command(ENDPOINT_EXTRAS, CMD_CHARGER_REBOOT)

    # ---- /rfid (spec 4.11) ----

    async def async_get_rfid_status(self) -> dict[str, Any]:
        """Return the rfid_status block (spec 4.11.2)."""
        payload = await self._request("GET", ENDPOINT_RFID_STATUS)
        status = payload.get("rfid_status")
        if not isinstance(status, dict):
            raise VoltieChargerConnectionError(
                "Charger returned no rfid_status block"
            )
        return status

    async def async_get_rfid_tags(
        self,
        *,
        first_item: int | None = None,
        max_count: int | None = None,
    ) -> dict[str, Any]:
        """Return the raw GET /rfid payload (rfid_list, rfid_count, list_hash)."""
        params: dict[str, str] = {}
        if first_item is not None:
            params["first_item"] = str(first_item)
        if max_count is not None:
            params["max_count"] = str(max_count)
        return await self._request("GET", ENDPOINT_RFID, params=params or None)

    async def async_add_rfid_tag(
        self,
        tag_id: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        body = _rfid_body(tag_id, name=name, enabled=enabled, comment=comment)
        return await self._request("POST", ENDPOINT_RFID, json_body=body)

    async def async_modify_rfid_tag(
        self,
        tag_id: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        body = _rfid_body(tag_id, name=name, enabled=enabled, comment=comment)
        return await self._request("PUT", ENDPOINT_RFID, json_body=body)

    async def async_delete_rfid_tag(self, tag_id: str) -> dict[str, Any]:
        return await self._request(
            "DELETE", ENDPOINT_RFID, params={"id": tag_id}
        )

    async def async_rfid_learn(
        self,
        *,
        timeout_sec: int | None = None,
        count_max: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if timeout_sec is not None:
            params["timeout_sec"] = timeout_sec
        if count_max is not None:
            params["count_max"] = count_max
        return await self._async_command(
            ENDPOINT_RFID_EXTRAS, CMD_RFID_LEARN, params or None
        )

    async def async_rfid_learn_cancel(self) -> dict[str, Any]:
        return await self._async_command(
            ENDPOINT_RFID_EXTRAS, CMD_RFID_LEARN_CANCEL
        )


def _rfid_body(
    tag_id: str,
    *,
    name: str | None,
    enabled: bool | None,
    comment: str | None,
) -> dict[str, Any]:
    """Build an RFID add/modify body, omitting fields the caller left out.

    PUT treats absent fields as "leave unchanged" (spec 4.11.4), so unset
    optional arguments must not be sent at all.
    """
    body: dict[str, Any] = {"id": tag_id}
    if name is not None:
        body["name"] = name
    if enabled is not None:
        body["enabled"] = enabled
    if comment is not None:
        body["comment"] = comment
    return body
