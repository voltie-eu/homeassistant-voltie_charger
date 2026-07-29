"""Switch platform for Voltie Charger."""
from __future__ import annotations

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
    VoltieChargerUnsupportedError,
)
from .const import (
    DATA_STATUS,
    FORCE_SINGLE_PHASE_NOT_SUPPORTED,
    FORCE_SINGLE_PHASE_OFF,
    FORCE_SINGLE_PHASE_ON,
)
from .entity import VoltieChargerConfigEntity, VoltieChargerEntity

_WRITE_ERRORS = (
    VoltieChargerAuthError,
    VoltieChargerConnectionError,
    VoltieChargerRejectedError,
)


@dataclass(frozen=True, kw_only=True)
class VoltieConfigSwitchDescription(SwitchEntityDescription):
    """Switch backed by a plain boolean key in /config."""

    config_key: str


CONFIG_SWITCHES: tuple[VoltieConfigSwitchDescription, ...] = (
    VoltieConfigSwitchDescription(
        key="autostart",
        translation_key="autostart",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_autostart_enabled",
    ),
    VoltieConfigSwitchDescription(
        key="display",
        translation_key="display",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_disp_enabled",
    ),
    VoltieConfigSwitchDescription(
        key="front_led",
        translation_key="front_led",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_front_led_enabled",
    ),
    VoltieConfigSwitchDescription(
        key="rear_led",
        translation_key="rear_led",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_rear_led_enabled",
    ),
    VoltieConfigSwitchDescription(
        key="buzzer",
        translation_key="buzzer",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_buzzer_enabled",
    ),
    VoltieConfigSwitchDescription(
        key="out_of_service",
        translation_key="out_of_service",
        entity_category=EntityCategory.CONFIG,
        # Not inverted: the entity is named after the out-of-service condition,
        # so on == charger blocked, matching the raw API value.
        config_key="conf_out_of_service",
    ),
)


def _to_ha_error(exc: Exception) -> HomeAssistantError:
    if isinstance(exc, VoltieChargerAuthError):
        return HomeAssistantError(f"Authentication failed: {exc}")
    # Checked before the rejected case it subclasses, so "too old firmware"
    # doesn't get reported as a parameter problem the user could fix.
    if isinstance(exc, VoltieChargerUnsupportedError):
        return HomeAssistantError(
            f"This charger's firmware does not support that feature: {exc}"
        )
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
    entities: list[SwitchEntity] = [
        VoltieChargerChargingSwitch(coordinator),
        VoltieChargerForceSinglePhaseSwitch(coordinator),
    ]
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
        except _WRITE_ERRORS as exc:
            raise _to_ha_error(exc) from exc
        await self.coordinator.async_request_refresh()


class VoltieChargerConfigSwitch(VoltieChargerConfigEntity, SwitchEntity):
    """A switch backed by a key in the charger's /config."""

    entity_description: VoltieConfigSwitchDescription
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
        description: VoltieConfigSwitchDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.config_key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._push(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._push(False)

    async def _push(self, value: bool) -> None:
        try:
            await self.coordinator.async_push_config({self._config_key: value})
        except _WRITE_ERRORS as exc:
            raise _to_ha_error(exc) from exc


class VoltieChargerForceSinglePhaseSwitch(VoltieChargerConfigEntity, SwitchEntity):
    """Force single-phase charging (spec 4.7).

    Reads as a four-state enum, but only 0/1 are writable; 2 and 3 report that
    the hardware cannot do it or that the firmware has not determined it yet.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "force_single_phase"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VoltieChargerCoordinator) -> None:
        super().__init__(
            coordinator, "force_single_phase", "conf_force_single_phase"
        )

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self._raw_value != FORCE_SINGLE_PHASE_NOT_SUPPORTED

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value
        if value == FORCE_SINGLE_PHASE_ON:
            return True
        if value == FORCE_SINGLE_PHASE_OFF:
            return False
        # 3/unknown (or an unrecognised code) has no boolean meaning, so report
        # unknown rather than guessing "off".
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._push(FORCE_SINGLE_PHASE_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._push(FORCE_SINGLE_PHASE_OFF)

    async def _push(self, value: int) -> None:
        # The firmware also refuses this parameter while a session is running or
        # the EVSE is faulted. We deliberately don't predict that: it would mean
        # reimplementing firmware state rules that can drift, and gating the
        # switch on them would make it flap in and out mid-session. The
        # accepted-count check in client.async_set_config turns an actual
        # refusal into an actionable error instead.
        try:
            await self.coordinator.async_push_config({self._config_key: value})
        except _WRITE_ERRORS as exc:
            raise _to_ha_error(exc) from exc
