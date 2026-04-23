"""Switch platform for Voltie Charger."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
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
)
from .const import DATA_CONFIG, DATA_STATUS
from .entity import VoltieChargerEntity


@dataclass(frozen=True, kw_only=True)
class VoltieConfigSwitchDescription(SwitchEntityDescription):
    """Switch backed by a writable key in /config."""

    config_key: str
    value_fn: Callable[[dict[str, Any]], bool | None]


CONFIG_SWITCHES: tuple[VoltieConfigSwitchDescription, ...] = (
    VoltieConfigSwitchDescription(
        key="autostart",
        translation_key="autostart",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_autostart_enabled",
        value_fn=lambda d: d.get("conf_autostart_enabled"),
    ),
    VoltieConfigSwitchDescription(
        key="display",
        translation_key="display",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_disp_enabled",
        value_fn=lambda d: d.get("conf_disp_enabled"),
    ),
    VoltieConfigSwitchDescription(
        key="front_led",
        translation_key="front_led",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_front_led_enabled",
        value_fn=lambda d: d.get("conf_front_led_enabled"),
    ),
    VoltieConfigSwitchDescription(
        key="rear_led",
        translation_key="rear_led",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_rear_led_enabled",
        value_fn=lambda d: d.get("conf_rear_led_enabled"),
    ),
    VoltieConfigSwitchDescription(
        key="buzzer",
        translation_key="buzzer",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_buzzer_enabled",
        value_fn=lambda d: d.get("conf_buzzer_enabled"),
    ),
)


def _to_ha_error(exc: Exception) -> HomeAssistantError:
    if isinstance(exc, VoltieChargerAuthError):
        return HomeAssistantError(f"Authentication failed: {exc}")
    if isinstance(exc, VoltieChargerRejectedError):
        return HomeAssistantError(f"Charger rejected the change: {exc}")
    if isinstance(exc, VoltieChargerConnectionError):
        return HomeAssistantError(f"Cannot reach charger: {exc}")
    return HomeAssistantError(str(exc))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VoltieChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Voltie Charger switches."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [VoltieChargerChargingSwitch(coordinator)]
    entities.extend(
        VoltieChargerConfigSwitch(coordinator, desc) for desc in CONFIG_SWITCHES
    )
    async_add_entities(entities)


class VoltieChargerChargingSwitch(VoltieChargerEntity, SwitchEntity):
    """Enable/disable charging via /start and /stop."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "charging"

    def __init__(self, coordinator: VoltieChargerCoordinator) -> None:
        # Base class builds unique_id from this key; "switch" preserves the
        # entity registry entry from earlier releases.
        super().__init__(coordinator, "switch")

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get(DATA_STATUS, {})
        value = status.get("charge_enabled")
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(self.coordinator.client.async_start)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(self.coordinator.client.async_stop)

    async def _send(self, func) -> None:
        try:
            await func()
        except (
            VoltieChargerAuthError,
            VoltieChargerConnectionError,
            VoltieChargerRejectedError,
        ) as exc:
            raise _to_ha_error(exc) from exc
        await self.coordinator.async_request_refresh()


class VoltieChargerConfigSwitch(VoltieChargerEntity, SwitchEntity):
    """A switch backed by a key in the charger's /config."""

    entity_description: VoltieConfigSwitchDescription
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
        description: VoltieConfigSwitchDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Config entities are unavailable if /config never returned anything."""
        if not super().available:
            return False
        config = (self.coordinator.data or {}).get(DATA_CONFIG) or {}
        return self.entity_description.config_key in config

    @property
    def is_on(self) -> bool | None:
        config = (self.coordinator.data or {}).get(DATA_CONFIG, {})
        value = self.entity_description.value_fn(config)
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._push(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._push(False)

    async def _push(self, value: bool) -> None:
        try:
            await self.coordinator.async_push_config(
                {self.entity_description.config_key: value}
            )
        except (
            VoltieChargerAuthError,
            VoltieChargerConnectionError,
            VoltieChargerRejectedError,
        ) as exc:
            raise _to_ha_error(exc) from exc
