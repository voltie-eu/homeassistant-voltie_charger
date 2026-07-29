"""Select platform for Voltie Charger — the enum keys in /config."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
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
from .const import ACCESS_MODES, DLM_MODES
from .entity import VoltieChargerConfigEntity


@dataclass(frozen=True, kw_only=True)
class VoltieSelectDescription(SelectEntityDescription):
    """Select backed by an integer enum key in /config."""

    config_key: str
    value_map: Mapping[int, str]
    # Precomputed inverse of value_map so writes don't rebuild it per call.
    slug_map: Mapping[str, int]


def _slug_map(modes: Mapping[int, str]) -> dict[str, int]:
    return {slug: value for value, slug in modes.items()}


SELECTS: tuple[VoltieSelectDescription, ...] = (
    VoltieSelectDescription(
        key="dlm_mode",
        translation_key="dlm_mode",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_dlm_mode",
        options=list(DLM_MODES.values()),
        value_map=DLM_MODES,
        slug_map=_slug_map(DLM_MODES),
    ),
    VoltieSelectDescription(
        key="access_mode",
        translation_key="access_mode",
        entity_category=EntityCategory.CONFIG,
        config_key="conf_access_mode",
        options=list(ACCESS_MODES.values()),
        value_map=ACCESS_MODES,
        slug_map=_slug_map(ACCESS_MODES),
    ),
)


def _to_ha_error(exc: Exception) -> HomeAssistantError:
    # Unsupported subclasses Rejected, so it has to be matched first.
    if isinstance(exc, VoltieChargerUnsupportedError):
        return HomeAssistantError(
            f"This charger's firmware does not support this setting: {exc}"
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
    """Set up Voltie Charger selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        VoltieChargerSelect(coordinator, description) for description in SELECTS
    )


class VoltieChargerSelect(VoltieChargerConfigEntity, SelectEntity):
    """An enum /config parameter exposed as a select."""

    entity_description: VoltieSelectDescription

    def __init__(
        self,
        coordinator: VoltieChargerCoordinator,
        description: VoltieSelectDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.config_key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        try:
            value = int(self._raw_value)
        except (TypeError, ValueError):
            return None
        # A code we don't know means newer firmware added a mode; report it as
        # unknown rather than raising or logging on every poll.
        return self.entity_description.value_map.get(value)

    async def async_select_option(self, option: str) -> None:
        # The service layer validates against options, but a direct call
        # doesn't — never push None to the charger.
        value = self.entity_description.slug_map.get(option)
        if value is None:
            raise HomeAssistantError(f"Unsupported option: {option}")

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
