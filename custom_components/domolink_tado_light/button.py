"""Button platform for DomoLink-Tado-Light."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up button entities."""
    coordinator: DomoLinkTadoLightCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []

    # Boutons globaux
    entities.append(DomoLinkResumeAllButton(coordinator, entry))
    entities.append(DomoLinkTurnOffAllButton(coordinator, entry))
    entities.append(DomoLinkSmartBoostAllButton(coordinator, entry))

    # Boutons par pièce
    for room in coordinator.rooms_config:
        room_id = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME, "unknown")
        room_name = room.get(CONF_ROOM_NAME, room_id)

        entities.append(DomoLinkSmartBoostRoomButton(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkResumeRoomButton(coordinator, entry, room_id, room_name))

    async_add_entities(entities)


# =============================================================================
# BOUTONS GLOBAUX
# =============================================================================

class DomoLinkResumeAllButton(CoordinatorEntity[DomoLinkTadoLightCoordinator], ButtonEntity):
    """Button to resume schedule across all rooms."""

    _attr_icon = "mdi:calendar-sync"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_resume_all_schedules"
        self._attr_name = f"{NAME} Reprendre programmation partout"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=NAME,
            manufacturer="SocrateMobile",
            model="Climate Central Companion",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_resume_all_schedules()


class DomoLinkTurnOffAllButton(CoordinatorEntity[DomoLinkTadoLightCoordinator], ButtonEntity):
    """Button to turn off (frost protection) all rooms."""

    _attr_icon = "mdi:power"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_turn_off_all"
        self._attr_name = f"{NAME} Tout éteindre (Hors-gel)"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=NAME,
            manufacturer="SocrateMobile",
            model="Climate Central Companion",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_turn_off_all()


class DomoLinkSmartBoostAllButton(CoordinatorEntity[DomoLinkTadoLightCoordinator], ButtonEntity):
    """Button to activate smart boost for all rooms."""

    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_smart_boost_all"
        self._attr_name = f"{NAME} Boost Intelligent Maison"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=NAME,
            manufacturer="SocrateMobile",
            model="Climate Central Companion",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_smart_boost()


# =============================================================================
# BOUTONS PAR PIÈCE
# =============================================================================

class DomoLinkSmartBoostRoomButton(CoordinatorEntity[DomoLinkTadoLightCoordinator], ButtonEntity):
    """Button to boost temperature in a specific room."""

    _attr_icon = "mdi:thermometer-plus"

    def __init__(
        self,
        coordinator: DomoLinkTadoLightCoordinator,
        entry: ConfigEntry,
        room_id: str,
        room_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.room_id = room_id
        self.room_name = room_name
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_smart_boost"
        self._attr_name = f"{room_name} Boost Intelligent"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{self.room_id}")},
            name=f"DomoLink {self.room_name}",
            manufacturer="SocrateMobile",
            model="Climate Room Companion",
            via_device=(DOMAIN, self.entry.entry_id),
        )

    async def async_press(self) -> None:
        await self.coordinator.async_smart_boost(room_id=self.room_id)


class DomoLinkResumeRoomButton(CoordinatorEntity[DomoLinkTadoLightCoordinator], ButtonEntity):
    """Button to resume schedule in a specific room."""

    _attr_icon = "mdi:calendar-check"

    def __init__(
        self,
        coordinator: DomoLinkTadoLightCoordinator,
        entry: ConfigEntry,
        room_id: str,
        room_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.room_id = room_id
        self.room_name = room_name
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_resume_schedule"
        self._attr_name = f"{room_name} Reprendre programmation"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{self.room_id}")},
            name=f"DomoLink {self.room_name}",
            manufacturer="SocrateMobile",
            model="Climate Room Companion",
            via_device=(DOMAIN, self.entry.entry_id),
        )

    async def async_press(self) -> None:
        await self.coordinator.async_resume_room_schedule(self.room_id)
