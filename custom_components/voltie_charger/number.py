"""Number platform for Voltie Charger — writable numeric /config parameters."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTime,
)
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
    CURRENT_LIMIT_MAX,
    CURRENT_LIMIT_MIN,
    CURRENT_LIMIT_STEP,
    DLM_CURRENT_LIMIT_MAX,
    DLM_CURRENT_LIMIT_MIN,
    ECO_START_CURRENT_MAX,
    ECO_START_CURRENT_MIN,
    GRID_TIMEOUT_MAX,
    GRID_TIMEOUT_MIN,
    GRID_VOLTAGE_MAX,
    GRID_VOLTAGE_MIN,
)
from .entity import VoltieChargerConfigEntity


@dataclass(frozen=True, kw_only=True)
class VoltieNumberDescription(NumberEntityDescription):
    """Number backed by a writable key in /config."""

    config_key: str
    # Reads an upper bound out of /status. Only set where the hardware reports
    # one; otherwise native_max_value stays at the static spec bound.
    max_value_fn: Callable[[dict[str, Any]], float | None] | None = None


def _hw_current_limit(status: dict[str, Any]) -> float | None:
    """Return the charger's own current ceiling, or None to keep the static max.

    Only ever lowers the bound. The API caps conf_current_limit at 6..32 A
    (spec 5.4) regardless of what the hardware reports, and PUT /config
    silently drops an out-of-range value, so offering more than 32 A would
    advertise a range whose upper part can never be written.
    """
    value = status.get("current_hw_limit")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    # A ceiling under the floor would leave nothing selectable and make the
    # entity unusable, so a nonsensical reading falls back to the static max.
    if value < CURRENT_LIMIT_MIN:
        return None
    return float(min(value, CURRENT_LIMIT_MAX))


NUMBERS: tuple[VoltieNumberDescription, ...] = (
    VoltieNumberDescription(
        key="current_limit",
        translation_key="current_limit",
        config_key="conf_current_limit",
        device_class=NumberDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=CURRENT_LIMIT_MIN,
        native_max_value=CURRENT_LIMIT_MAX,
        max_value_fn=_hw_current_limit,
    ),
    # Building-side limit, not a hardware property: fixed 6..32 A per spec 5.4.
    VoltieNumberDescription(
        key="dlm_current_limit",
        translation_key="dlm_current_limit",
        config_key="conf_dlm_current_limit",
        device_class=NumberDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=DLM_CURRENT_LIMIT_MIN,
        native_max_value=DLM_CURRENT_LIMIT_MAX,
    ),
    VoltieNumberDescription(
        key="dlm_eco_startcurr",
        translation_key="dlm_eco_startcurr",
        config_key="conf_dlm_eco_startcurr",
        device_class=NumberDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=ECO_START_CURRENT_MIN,
        native_max_value=ECO_START_CURRENT_MAX,
    ),
    VoltieNumberDescription(
        key="grid_u_stop",
        translation_key="grid_u_stop",
        config_key="conf_grid_u_stop",
        device_class=NumberDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        native_min_value=GRID_VOLTAGE_MIN,
        native_max_value=GRID_VOLTAGE_MAX,
    ),
    VoltieNumberDescription(
        key="grid_u_min",
        translation_key="grid_u_min",
        config_key="conf_grid_u_min",
        device_class=NumberDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        native_min_value=GRID_VOLTAGE_MIN,
        native_max_value=GRID_VOLTAGE_MAX,
    ),
    VoltieNumberDescription(
        key="grid_u_max",
        translation_key="grid_u_max",
        config_key="conf_grid_u_max",
        device_class=NumberDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        native_min_value=GRID_VOLTAGE_MIN,
        native_max_value=GRID_VOLTAGE_MAX,
    ),
    VoltieNumberDescription(
        key="grid_t_up",
        translation_key="grid_t_up",
        config_key="conf_grid_t_up",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=GRID_TIMEOUT_MIN,
        native_max_value=GRID_TIMEOUT_MAX,
    ),
    VoltieNumberDescription(
        key="grid_t_dn",
        translation_key="grid_t_dn",
        config_key="conf_grid_t_dn",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=GRID_TIMEOUT_MIN,
        native_max_value=GRID_TIMEOUT_MAX,
    ),
)


def _to_ha_error(exc: Exception) -> HomeAssistantError:
    # Checked before VoltieChargerRejectedError, which it subclasses.
    if isinstance(exc, VoltieChargerUnsupportedError):
        return HomeAssistantError(
            f"This charger's firmware does not support this setting; "
            f"a firmware update is required: {exc}"
        )
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
    """Set up Voltie Charger number entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        VoltieChargerNumber(coordinator, description) for description in NUMBERS
    )


class VoltieChargerNumber(VoltieChargerConfigEntity, NumberEntity):
    """A Voltie Charger /config number driven by a description."""

    entity_description: VoltieNumberDescription

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    # Every parameter here is a whole-unit integer (spec 5.4).
    _attr_native_step = CURRENT_LIMIT_STEP

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
        description: VoltieNumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.config_key)
        self.entity_description = description

    @property
    def native_max_value(self) -> float:
        fn = self.entity_description.max_value_fn
        if fn is not None and (dynamic := fn(self._status)) is not None:
            return dynamic
        return super().native_max_value

    @property
    def native_value(self) -> float | None:
        value = self._raw_value
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.async_push_config(
                {self.entity_description.config_key: int(value)}
            )
        except (
            VoltieChargerAuthError,
            VoltieChargerConnectionError,
            VoltieChargerRejectedError,
        ) as exc:
            raise _to_ha_error(exc) from exc
