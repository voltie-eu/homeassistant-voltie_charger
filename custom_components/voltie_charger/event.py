"""Event platform for Voltie Charger — the end of a charging session."""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VoltieChargerConfigEntry, VoltieChargerCoordinator
from .const import EVENT_SESSION_FINISHED
from .entity import VoltieChargerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VoltieChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Voltie Charger event entity."""
    async_add_entities([VoltieChargerSessionEvent(entry.runtime_data)])


class VoltieChargerSessionEvent(VoltieChargerEntity, EventEntity):
    """Fires session_finished once per charging session, with its totals.

    A session runs from plug-in to unplug; the coordinator detects its end and
    fetches the closed record.
    """

    _attr_translation_key = "charging_session"
    _attr_event_types = [EVENT_SESSION_FINISHED]

    def __init__(self, coordinator: VoltieChargerCoordinator) -> None:
        super().__init__(coordinator, "charging_session")
        # Start of the last session reported, restored across restarts so a
        # session is never reported twice.
        self._last_reported: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_event_data()) and (
            attributes := last.last_event_attributes
        ):
            self._last_reported = attributes.get("session_start")
        # The first refresh ran before this entity existed, so a session that
        # ended while Home Assistant was down is already waiting.
        self._report(self.coordinator.finished_session)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._report(self.coordinator.finished_session)
        super()._handle_coordinator_update()

    def _report(self, session: dict[str, Any] | None) -> None:
        if session is None or session.get("session_start") == self._last_reported:
            return
        self._trigger_event(EVENT_SESSION_FINISHED, session)
        self._last_reported = session.get("session_start")
