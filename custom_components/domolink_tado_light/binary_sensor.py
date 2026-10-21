"""Binary sensor platform for DomoLink-Tado-Light."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOM_ID, CONF_ROOM_NAME, CONF_ROOMS, DOMAIN, NAME
from .coordinator import DomoLinkTadoLightCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    coordinator: DomoLinkTadoLightCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []

    # Binaire global
    entities.append(DomoLinkEcoModeBinarySensor(coordinator, entry))

    # Binaires par pièce
    for room in coordinator.rooms_config:
        room_id = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME, "unknown")
        room_name = room.get(CONF_ROOM_NAME, room_id)

        entities.append(DomoLinkMoldRiskBinarySensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkVentilationBinarySensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkWindowCutBinarySensor(coordinator, entry, room_id, room_name))

    async_add_entities(entities)


class DomoLinkBaseRoomBinarySensor(CoordinatorEntity[DomoLinkTadoLightCoordinator], BinarySensorEntity):
    """Base class for room binary sensors."""

    def __init__(
        self,
        coordinator: DomoLinkTadoLightCoordinator,
        entry: ConfigEntry,
        room_id: str,
        room_name: str,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self.room_id = room_id
        self.room_name = room_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{self.room_id}")},
            name=f"DomoLink {self.room_name}",
            manufacturer="SocrateMobile",
            model="Climate Room Companion",
            via_device=(DOMAIN, self.entry.entry_id),
        )

    @property
    def room_data(self) -> dict[str, Any]:
        """Get room data."""
        rooms = self.coordinator.data.get("rooms", {})
        return rooms.get(self.room_id, {})


class DomoLinkMoldRiskBinarySensor(DomoLinkBaseRoomBinarySensor):
    """Binary sensor for mold risk problem."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-rhombus-outline"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_mold_risk_problem"
        self._attr_name = f"{room_name} Alerte moisissure"

    @property
    def is_on(self) -> bool:
        return bool(self.room_data.get("mold_risk_problem", False))


class DomoLinkVentilationBinarySensor(DomoLinkBaseRoomBinarySensor):
    """Binary sensor indicating if ventilation is recommended."""

    _attr_icon = "mdi:air-filter"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_ventilation_recommended"
        self._attr_name = f"{room_name} Aération recommandée"

    @property
    def is_on(self) -> bool:
        return bool(self.room_data.get("ventilation_recommended", False))


class DomoLinkWindowCutBinarySensor(DomoLinkBaseRoomBinarySensor):
    """Binary sensor indicating if heating is currently cut due to an open window."""

    _attr_icon = "mdi:window-open"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_window_cut_active"
        self._attr_name = f"{room_name} Coupure fenêtre active"

    @property
    def is_on(self) -> bool:
        return bool(self.room_data.get("window_cut_active", False))


# =============================================================================
# BINAIRE GLOBAL
# =============================================================================

class DomoLinkEcoModeBinarySensor(CoordinatorEntity[DomoLinkTadoLightCoordinator], BinarySensorEntity):
    """Binary sensor indicating if global eco mode is currently active."""

    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_eco_mode_active"
        self._attr_name = f"{NAME} Mode Éco Global Actif"
        self.entry = entry

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
