"""Switch platform for DomoLink-Tado-Light."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import DomoLinkTadoLightCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    coordinator: DomoLinkTadoLightCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [
        DomoLinkGlobalEcoSwitch(coordinator, entry),
        DomoLinkWindowProtectionSwitch(coordinator, entry),
        DomoLinkAdaptivePreheatSwitch(coordinator, entry),
    ]
    async_add_entities(entities)


class DomoLinkGlobalEcoSwitch(CoordinatorEntity[DomoLinkTadoLightCoordinator], SwitchEntity):
    """Switch for toggling global Eco mode across all rooms."""

    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_global_eco_switch"
        self._attr_name = f"{NAME} Mode Éco Global"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=NAME,
            manufacturer="SocrateMobile",
            model="Climate Central Companion",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("eco_mode_active", False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_eco_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_eco_mode(False)


class DomoLinkWindowProtectionSwitch(CoordinatorEntity[DomoLinkTadoLightCoordinator], SwitchEntity):
    """Switch to toggle automatic heating cutoff on open window."""

    _attr_icon = "mdi:window-closed-variant"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_window_protection_switch"
        self._attr_name = f"{NAME} Protection Coupure Fenêtres"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=NAME,
            manufacturer="SocrateMobile",
            model="Climate Central Companion",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("window_protection_enabled", True))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_window_protection(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_window_protection(False)


class DomoLinkAdaptivePreheatSwitch(CoordinatorEntity[DomoLinkTadoLightCoordinator], SwitchEntity):
    """Switch to toggle autonomous adaptive preheating."""

    _attr_icon = "mdi:clock-fast"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_adaptive_preheat_switch"
        self._attr_name = f"{NAME} Préchauffage Adaptatif Autonome"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=NAME,
            manufacturer="SocrateMobile",
            model="Climate Central Companion",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("preheat_autonomous_enabled", False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_adaptive_preheat(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_adaptive_preheat(False)
