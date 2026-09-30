"""Tracking of charging sessions, for the session_finished event."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
import math
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .client import VoltieChargerError
from .const import DOMAIN, SESSION_STORE_VERSION

_LOGGER = logging.getLogger(__name__)

# What survives a restart. The CDR ID alone cannot identify a session: the
# firmware renumbers an active one when it resyncs its ID counter with the
# server or archives its records, so the start time is what identifies it.
_IDENTITY_KEYS = ("charger_id", "s_start", "cdr_id")


def _number(value: Any) -> int | float | None:
    """A finite, non-negative number, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _timestamp(value: Any) -> str | None:
    seconds = _number(value)
    if not seconds:
        return None
    return dt_util.utc_from_timestamp(seconds).isoformat()


def _session_start(cdr: dict[str, Any]) -> int | float | None:
    # The firmware only reports a record as active once its start is set.
    return _number(cdr.get("s_start")) or None


def _identity(session: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if session is None:
        return None
    return tuple(session.get(key) for key in _IDENTITY_KEYS)


def session_summary(cdr: dict[str, Any]) -> dict[str, Any]:
    """Event attributes describing a finished session."""
    cdr_id = cdr.get("cdr_id")
    idtag_name = cdr.get("idtag_name")
    return {
        "cdr_id": (
            cdr_id if isinstance(cdr_id, int) and not isinstance(cdr_id, bool) else None
        ),
        "session_start": _timestamp(cdr.get("s_start")),
        # Only closed records carry s_end, so a fallback snapshot has none.
        "session_end": _timestamp(cdr.get("s_end")),
        "energy_kwh": _number(cdr.get("chg_energy")),
        "charge_time_s": _number(cdr.get("chg_time")),
        "idle_time_s": _number(cdr.get("idle_time")),
        "avg_power_kw": _number(cdr.get("avg_power")),
        "max_power_kw": _number(cdr.get("max_power")),
        "idtag_name": (
            idtag_name if isinstance(idtag_name, str) and idtag_name else None
        ),
        # Set when a charger restart cut the session short; the firmware may
        # carry on charging in a new session.
        "closed_after_restart": cdr.get("closed_after_restart") is True,
    }


class SessionTracker:
    """Follows the charger's active session and reports it once it ends."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, SESSION_STORE_VERSION, f"{DOMAIN}.{entry_id}.session"
        )
        # The active record as last seen. Only its identity is persisted, so
        # after a restart the values are gone until the charger reports them.
        self._session: dict[str, Any] | None = None

    async def async_load(self) -> None:
        data = await self._store.async_load()
        session = (data or {}).get("session")
        if isinstance(session, dict) and _session_start(session) is not None:
            self._session = session

    async def async_update(
        self,
        status: dict[str, Any],
        fetch_cdr: Callable[[int], Awaitable[dict[str, Any] | None]],
    ) -> dict[str, Any] | None:
        """Take a /status reading; return the summary of a session it ended."""
        # Only an explicit record or an explicit null says anything about the
        # session; a response without the key, or a malformed record, keeps
        # the tracked one rather than ending it.
        if "cdr" not in status:
            return None
        cdr = status["cdr"]
        if cdr is not None and not (
            isinstance(cdr, dict) and _session_start(cdr) is not None
        ):
            return None

        charger_id = status.get("charger_id")
        tracked = self._session
        if (
            tracked is not None
            and charger_id is not None
            and tracked.get("charger_id") not in (None, charger_id)
        ):
            # A different charger answers at this address now.
            tracked = None

        finished = None
        if tracked is not None and (
            cdr is None or _session_start(cdr) != _session_start(tracked)
        ):
            finished = await self._async_final_record(tracked, status, fetch_cdr)

        current = None if cdr is None else {**cdr, "charger_id": charger_id}
        if _identity(current) != _identity(self._session):
            self._store.async_delay_save(self._data, 0)
        self._session = current
        return finished

    async def _async_final_record(
        self,
        tracked: dict[str, Any],
        status: dict[str, Any],
        fetch_cdr: Callable[[int], Awaitable[dict[str, Any] | None]],
    ) -> dict[str, Any]:
        """Prefer the closed record over the last poll's snapshot.

        The snapshot misses up to a poll interval of the session and never has
        its end time. last_cdr names the most recently closed record, which is
        normally this one; the tracked ID covers a renumbering in between.
        """
        candidates: list[int] = []
        for cdr_id in (status.get("last_cdr"), tracked.get("cdr_id")):
            if (
                isinstance(cdr_id, int)
                and not isinstance(cdr_id, bool)
                and cdr_id > 0
                and cdr_id not in candidates
            ):
                candidates.append(cdr_id)
        for cdr_id in candidates:
            try:
                record = await fetch_cdr(cdr_id)
            except VoltieChargerError as exc:
                _LOGGER.debug("Could not fetch CDR %s: %s", cdr_id, exc)
                continue
            if record is not None and _session_start(record) == _session_start(
                tracked
            ):
                return session_summary(record)
        return session_summary(tracked)

    def _data(self) -> dict[str, Any]:
        session = self._session
        return {
            "session": (
                None
                if session is None
                else {key: session.get(key) for key in _IDENTITY_KEYS}
            )
        }

    async def async_flush(self) -> None:
        """Write the tracked session now, cancelling any pending write."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        await self._store.async_remove()
