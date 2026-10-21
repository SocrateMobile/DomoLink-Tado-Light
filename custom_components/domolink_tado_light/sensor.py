"""Sensor platform for DomoLink-Tado-Light."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
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
    """Set up sensor entities."""
    coordinator: DomoLinkTadoLightCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # Capteurs globaux
    entities.append(DomoLinkAverageTempSensor(coordinator, entry))
    entities.append(DomoLinkActiveRoomsSensor(coordinator, entry))

    # Capteurs par pièce
    for room in coordinator.rooms_config:
        room_id = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME, "unknown")
        room_name = room.get(CONF_ROOM_NAME, room_id)

        entities.append(DomoLinkDewPointSensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkAbsoluteHumiditySensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkMoldRiskLevelSensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkVentilationAdviceSensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkTempDeltaSensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkPreheatDurationSensor(coordinator, entry, room_id, room_name))
        entities.append(DomoLinkHeatingRateSensor(coordinator, entry, room_id, room_name))

    async_add_entities(entities)


class DomoLinkBaseRoomSensor(CoordinatorEntity[DomoLinkTadoLightCoordinator], SensorEntity):
    """Base class for room sensors."""

    def __init__(
        self,
        coordinator: DomoLinkTadoLightCoordinator,
        entry: ConfigEntry,
        room_id: str,
        room_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self.room_id = room_id
        self.room_name = room_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the room."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{self.room_id}")},
            name=f"DomoLink {self.room_name}",
            manufacturer="SocrateMobile",
            model="Climate Room Companion",
            via_device=(DOMAIN, self.entry.entry_id),
        )

    @property
    def room_data(self) -> dict[str, Any]:
        """Get coordinator data for this room."""
        rooms = self.coordinator.data.get("rooms", {})
        return rooms.get(self.room_id, {})


class DomoLinkDewPointSensor(DomoLinkBaseRoomSensor):
    """Dew point sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:water-thermometer"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_dew_point"
        self._attr_name = f"{room_name} Point de rosée"

    @property
    def native_value(self) -> float | None:
        return self.room_data.get("dew_point")


class DomoLinkAbsoluteHumiditySensor(DomoLinkBaseRoomSensor):
    """Absolute humidity sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "g/m³"
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_absolute_humidity"
        self._attr_name = f"{room_name} Humidité absolue"

    @property
    def native_value(self) -> float | None:
        return self.room_data.get("absolute_humidity")


class DomoLinkMoldRiskLevelSensor(DomoLinkBaseRoomSensor):
    """Mold risk level sensor."""

    _attr_icon = "mdi:alert-decagram-outline"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_mold_risk_level"
        self._attr_name = f"{room_name} Risque de moisissure"

    @property
    def native_value(self) -> str | None:
        return self.room_data.get("mold_risk_level")


class DomoLinkVentilationAdviceSensor(DomoLinkBaseRoomSensor):
    """Ventilation advice sensor."""

    _attr_icon = "mdi:window-open-variant"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_ventilation_advice"
        self._attr_name = f"{room_name} Conseil d'aération"

    @property
    def native_value(self) -> str:
        rec = self.room_data.get("ventilation_recommended")
        if rec is True:
            return "Recommandée"
        if rec is False:
            return "Non nécessaire"
        return "Indisponible"


class DomoLinkTempDeltaSensor(DomoLinkBaseRoomSensor):
    """Temperature delta sensor (target vs real indoor)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_temp_delta"
        self._attr_name = f"{room_name} Écart consigne / ambiance"

    @property
    def native_value(self) -> float | None:
        return self.room_data.get("temp_delta")


class DomoLinkPreheatDurationSensor(DomoLinkBaseRoomSensor):
    """Estimated preheat duration sensor."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_preheat_duration"
        self._attr_name = f"{room_name} Préchauffage estimé"

    @property
    def native_value(self) -> int:
        return self.room_data.get("preheat_duration", 0)


class DomoLinkHeatingRateSensor(DomoLinkBaseRoomSensor):
    """Observed heating rate sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°C/h"
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, entry, room_id, room_name):
        super().__init__(coordinator, entry, room_id, room_name)
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_heating_rate"
        self._attr_name = f"{room_name} Vitesse de chauffe"

    @property
    def native_value(self) -> float:
        return self.room_data.get("heating_rate", 1.5)


# =============================================================================
# CAPTEURS GLOBAUX
# =============================================================================

class DomoLinkAverageTempSensor(CoordinatorEntity[DomoLinkTadoLightCoordinator], SensorEntity):
    """Average indoor temperature across all configured rooms."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_average_indoor_temp"
        self._attr_name = f"{NAME} Température moyenne intérieure"
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
    def native_value(self) -> float | None:
        return self.coordinator.data.get("average_indoor_temp")


class DomoLinkActiveRoomsSensor(CoordinatorEntity[DomoLinkTadoLightCoordinator], SensorEntity):
    """Count of rooms currently heating."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: DomoLinkTadoLightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_active_heating_rooms"
        self._attr_name = f"{NAME} Pièces en chauffe"
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
    def native_value(self) -> int:
        return self.coordinator.data.get("active_heating_rooms", 0)
