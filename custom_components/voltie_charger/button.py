"""Button platform for Voltie Charger — one-shot commands."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VoltieChargerConfigEntry, VoltieChargerCoordinator
from .client import (
    VoltieChargerAuthError,
    VoltieChargerConnectionError,
    VoltieChargerRejectedError,
    VoltieChargerUnsupportedError,
)
from .entity import VoltieChargerEntity, VoltieChargerRfidEntity


@dataclass(frozen=True, kw_only=True)
class VoltieButtonDescription(ButtonEntityDescription):
    """Button description carrying the command to send on press."""

    press_fn: Callable[[VoltieChargerCoordinator], Coroutine[Any, Any, Any]]
    refresh_after: bool = True


BUTTONS: tuple[VoltieButtonDescription, ...] = (
    VoltieButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.client.async_reboot(),
        # The charger drops off the network for ~5 s, so an immediate poll would
        # fail and noisily mark every entity unavailable. The next scheduled
        # refresh picks the device back up on its own.
        refresh_after=False,
    ),
)

RFID_BUTTONS: tuple[VoltieButtonDescription, ...] = (
    VoltieButtonDescription(
        key="rfid_learn",
        translation_key="rfid_learn",
        # No arguments: the firmware defaults (30 s, unlimited tags) apply. The
        # voltie_charger.start_rfid_learn service takes timeout_sec/count_max
        # for callers that need them.
        press_fn=lambda c: c.client.async_rfid_learn(),
    ),
    VoltieButtonDescription(
        key="rfid_learn_cancel",
        translation_key="rfid_learn_cancel",
        press_fn=lambda c: c.client.async_rfid_learn_cancel(),
    ),
)


def _to_ha_error(exc: Exception) -> HomeAssistantError:
    if isinstance(exc, VoltieChargerAuthError):
        return HomeAssistantError(f"Authentication failed: {exc}")
    # Tested before the rejected branch it subclasses: the remedy is a firmware
    # update, not a retry.
    if isinstance(exc, VoltieChargerUnsupportedError):
        return HomeAssistantError(
            "The charger firmware does not support this command; update the "
            f"charger firmware to use it ({exc})"
        )
    if isinstance(exc, VoltieChargerRejectedError):
        return HomeAssistantError(f"Charger rejected the command: {exc}")
    if isinstance(exc, VoltieChargerConnectionError):
        return HomeAssistantError(f"Cannot reach charger: {exc}")
    return HomeAssistantError(str(exc))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VoltieChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger buttons."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [
        VoltieChargerButton(coordinator, description) for description in BUTTONS
    ]
    if coordinator.rfid_supported:
        entities.extend(
            VoltieChargerRfidButton(coordinator, description)
            for description in RFID_BUTTONS
        )
    async_add_entities(entities)


class VoltieChargerButton(VoltieChargerEntity, ButtonEntity):
    """A one-shot command button driven by a description."""

    entity_description: VoltieButtonDescription

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
        description: VoltieButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self.coordinator)
        except (
            VoltieChargerAuthError,
            VoltieChargerConnectionError,
            VoltieChargerRejectedError,
        ) as exc:
            raise _to_ha_error(exc) from exc
        if self.entity_description.refresh_after:
            await self.coordinator.async_request_refresh()


# The RFID base is listed first so its /rfid/status availability check wins.
class VoltieChargerRfidButton(VoltieChargerRfidEntity, VoltieChargerButton):
    """An RFID command button, present only on API v5 firmware."""
