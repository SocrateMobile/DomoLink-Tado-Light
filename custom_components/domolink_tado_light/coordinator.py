"""DataUpdateCoordinator for DomoLink-Tado-Light."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_TEMPERATURE,
    DOMAIN as CLIMATE_DOMAIN,
    HVACMode,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_OPEN, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .adaptive_preheat import estimate_preheat_duration
from .const import (
    CONF_DEFAULT_ECO_TEMP,
    CONF_HEATING_RATE,
    CONF_OUTDOOR_HUMIDITY_ENTITY,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_ROOM_CLIMATE_ENTITY,
    CONF_ROOM_HUMIDITY_ENTITY,
    CONF_ROOM_ID,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_ENTITY,
    CONF_ROOM_WINDOW_ENTITY,
    CONF_ROOMS,
    CONF_SMART_BOOST_DURATION,
    CONF_SMART_BOOST_TEMP,
    DEFAULT_ECO_TEMP,
    DEFAULT_HEATING_RATE,
    DEFAULT_SMART_BOOST_DURATION,
    DEFAULT_SMART_BOOST_TEMP,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .physics import (
    calculate_absolute_humidity,
    calculate_dew_point,
    calculate_mold_risk_level,
    calculate_mold_risk_problem,
    calculate_ventilation_recommended,
)

_LOGGER = logging.getLogger(__name__)


class DomoLinkTadoLightCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage climate companion data and local calculations."""

    def __init__(self, hass: HomeAssistant, entry_data: dict[str, Any]) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )
        self.entry_data = entry_data
        self.rooms_config: list[dict[str, Any]] = entry_data.get(CONF_ROOMS, [])

        self.outdoor_temp_entity = entry_data.get(CONF_OUTDOOR_TEMP_ENTITY)
        self.outdoor_humidity_entity = entry_data.get(CONF_OUTDOOR_HUMIDITY_ENTITY)

        self.default_eco_temp = float(entry_data.get(CONF_DEFAULT_ECO_TEMP, DEFAULT_ECO_TEMP))
        self.smart_boost_temp = float(entry_data.get(CONF_SMART_BOOST_TEMP, DEFAULT_SMART_BOOST_TEMP))
        self.smart_boost_duration = int(entry_data.get(CONF_SMART_BOOST_DURATION, DEFAULT_SMART_BOOST_DURATION))

        # État interne global
        self.eco_mode_active = False
        self.window_protection_enabled = True
        self.preheat_autonomous_enabled = False

        # Sauvegardes d'états avant éco / fenêtre
        self._pre_eco_states: dict[str, dict[str, Any]] = {}
        self._window_cut_states: dict[str, dict[str, Any]] = {}

        # Suivi des timers de boost par pièce
        self._boost_cancel_callbacks: dict[str, CALLBACK_TYPE] = {}

        # Dictionnaire des écoutes d'états
        self._unsub_listeners: list[CALLBACK_TYPE] = []

    async def async_setup(self) -> None:
        """Set up entity listeners and initial state."""
        watched_entities: set[str] = set()

        if self.outdoor_temp_entity:
            watched_entities.add(self.outdoor_temp_entity)
        if self.outdoor_humidity_entity:
            watched_entities.add(self.outdoor_humidity_entity)

        for room in self.rooms_config:
            if room.get(CONF_ROOM_CLIMATE_ENTITY):
                watched_entities.add(room[CONF_ROOM_CLIMATE_ENTITY])
            if room.get(CONF_ROOM_TEMP_ENTITY):
                watched_entities.add(room[CONF_ROOM_TEMP_ENTITY])
            if room.get(CONF_ROOM_HUMIDITY_ENTITY):
                watched_entities.add(room[CONF_ROOM_HUMIDITY_ENTITY])
            if room.get(CONF_ROOM_WINDOW_ENTITY):
                watched_entities.add(room[CONF_ROOM_WINDOW_ENTITY])

        @callback
        def _handle_state_change(event: Event) -> None:
            """Handle entity state change in real time."""
            self.async_set_updated_data(self._calculate_all())

        if watched_entities:
            unsub = async_track_state_change_event(
                self.hass, list(watched_entities), _handle_state_change
            )
            self._unsub_listeners.append(unsub)

    def async_unload(self) -> None:
        """Unload coordinator and cancel active listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

        for cancel in self._boost_cancel_callbacks.values():
            cancel()
        self._boost_cancel_callbacks.clear()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and calculate data periodically."""
        return self._calculate_all()

    def _get_float_state(self, entity_id: str | None) -> float | None:
        """Get float value from entity state."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, None):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_bool_state(self, entity_id: str | None) -> bool:
        """Get bool value from binary sensor or switch."""
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.state in (STATE_ON, STATE_OPEN, "true", "1")

    def _calculate_all(self) -> dict[str, Any]:
        """Compute all room physics, comfort indices, and global metrics."""
        outdoor_temp = self._get_float_state(self.outdoor_temp_entity)
        outdoor_humidity = self._get_float_state(self.outdoor_humidity_entity)

        rooms_data: dict[str, dict[str, Any]] = {}
        total_indoor_temp = 0.0
        indoor_temp_count = 0
        active_heating_rooms = 0

        for room in self.rooms_config:
            room_id = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME, "unknown")
            climate_id = room.get(CONF_ROOM_CLIMATE_ENTITY)
            temp_id = room.get(CONF_ROOM_TEMP_ENTITY)
            hum_id = room.get(CONF_ROOM_HUMIDITY_ENTITY)
            window_id = room.get(CONF_ROOM_WINDOW_ENTITY)
            heating_rate = float(room.get(CONF_HEATING_RATE, DEFAULT_HEATING_RATE))

            climate_state = self.hass.states.get(climate_id) if climate_id else None

            # Température cible & actuelle depuis l'entité climate
            target_temp: float | None = None
            climate_current_temp: float | None = None
            hvac_mode: str | None = None

            if climate_state:
                hvac_mode = climate_state.state
                attrs = climate_state.attributes
                target_temp = attrs.get(ATTR_TEMPERATURE)
                climate_current_temp = attrs.get(ATTR_CURRENT_TEMPERATURE)

            # Température & Humidité réelles (priorité à la sonde d'ambiance externe)
            external_temp = self._get_float_state(temp_id)
            indoor_temp = external_temp if external_temp is not None else climate_current_temp

            external_humidity = self._get_float_state(hum_id)
            indoor_humidity = external_humidity

            # Calculs physiques
            dew_point = calculate_dew_point(indoor_temp, indoor_humidity)
            abs_humidity = calculate_absolute_humidity(indoor_temp, indoor_humidity)
            mold_level = calculate_mold_risk_level(indoor_temp, indoor_humidity)
            mold_problem = calculate_mold_risk_problem(indoor_temp, indoor_humidity)
            ventilation_rec = calculate_ventilation_recommended(
                indoor_temp, indoor_humidity, outdoor_temp, outdoor_humidity
            )

            # Écart consigne / réel
            temp_delta: float | None = None
            if target_temp is not None and indoor_temp is not None:
                temp_delta = round(target_temp - indoor_temp, 1)

            # Préchauffage estimé
            preheat_duration = estimate_preheat_duration(target_temp, indoor_temp, heating_rate)

            # État de la fenêtre
            window_open = self._get_bool_state(window_id)

            if indoor_temp is not None:
                total_indoor_temp += indoor_temp
                indoor_temp_count += 1

            # Détection pièce en chauffe
            if hvac_mode == HVACMode.HEAT or (hvac_mode == HVACMode.AUTO and temp_delta and temp_delta > 0.2):
                active_heating_rooms += 1

            rooms_data[room_id] = {
                "config": room,
                "indoor_temp": indoor_temp,
                "indoor_humidity": indoor_humidity,
                "climate_current_temp": climate_current_temp,
                "target_temp": target_temp,
                "hvac_mode": hvac_mode,
                "dew_point": dew_point,
                "absolute_humidity": abs_humidity,
                "mold_risk_level": mold_level,
                "mold_risk_problem": mold_problem,
                "ventilation_recommended": ventilation_rec,
                "temp_delta": temp_delta,
                "preheat_duration": preheat_duration,
                "heating_rate": heating_rate,
                "window_open": window_open,
                "window_cut_active": room_id in self._window_cut_states,
            }

            # Gestion automatique de coupure sur fenêtre ouverte
            if self.window_protection_enabled and window_id and climate_id:
                if window_open and room_id not in self._window_cut_states and hvac_mode != HVACMode.OFF:
                    self.hass.async_create_task(
                        self._async_handle_window_cut(room_id, climate_id, hvac_mode, target_temp)
                    )
                elif not window_open and room_id in self._window_cut_states:
                    self.hass.async_create_task(
                        self._async_restore_window_cut(room_id, climate_id)
                    )

        avg_temp = round(total_indoor_temp / indoor_temp_count, 1) if indoor_temp_count > 0 else None

        return {
            "rooms": rooms_data,
            "outdoor_temp": outdoor_temp,
            "outdoor_humidity": outdoor_humidity,
            "average_indoor_temp": avg_temp,
            "active_heating_rooms": active_heating_rooms,
            "eco_mode_active": self.eco_mode_active,
            "window_protection_enabled": self.window_protection_enabled,
            "preheat_autonomous_enabled": self.preheat_autonomous_enabled,
        }

    async def _async_handle_window_cut(
        self, room_id: str, climate_id: str, prev_mode: str, prev_temp: float | None
    ) -> None:
        """Turn off climate when window opens."""
        self._window_cut_states[room_id] = {
            "mode": prev_mode,
            "temp": prev_temp,
        }
        _LOGGER.info("Fenêtre ouverte détectée dans %s: mise hors-gel de %s", room_id, climate_id)
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: HVACMode.OFF},
            blocking=False,
        )

    async def _async_restore_window_cut(self, room_id: str, climate_id: str) -> None:
        """Restore climate state when window closes."""
        saved = self._window_cut_states.pop(room_id, None)
        if saved:
            target_mode = saved.get("mode") or HVACMode.AUTO
            _LOGGER.info("Fenêtre refermée dans %s: reprise du mode %s sur %s", room_id, target_mode, climate_id)
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_HVAC_MODE,
                {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: target_mode},
                blocking=False,
            )

    # =========================================================================
    # ACTIONS GLOBALES ET SERVICE CALLS
    # =========================================================================

    async def async_resume_all_schedules(self) -> None:
        """Resume schedule (AUTO mode) across all configured climate entities."""
        tasks = []
        for room in self.rooms_config:
            climate_id = room.get(CONF_ROOM_CLIMATE_ENTITY)
            if climate_id:
                tasks.append(
                    self.hass.services.async_call(
                        CLIMATE_DOMAIN,
                        SERVICE_SET_HVAC_MODE,
                        {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: HVACMode.AUTO},
                        blocking=False,
                    )
                )
        if tasks:
            await asyncio.gather(*tasks)
        self.eco_mode_active = False
        self.async_set_updated_data(self._calculate_all())

    async def async_resume_room_schedule(self, room_id: str) -> None:
        """Resume schedule for a specific room."""
        for room in self.rooms_config:
            rid = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME)
            if rid == room_id:
                climate_id = room.get(CONF_ROOM_CLIMATE_ENTITY)
                if climate_id:
                    await self.hass.services.async_call(
                        CLIMATE_DOMAIN,
                        SERVICE_SET_HVAC_MODE,
                        {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: HVACMode.AUTO},
                        blocking=False,
                    )
                break
        self.async_set_updated_data(self._calculate_all())

    async def async_turn_off_all(self) -> None:
        """Turn off (frost protection) all configured climate entities."""
        tasks = []
        for room in self.rooms_config:
            climate_id = room.get(CONF_ROOM_CLIMATE_ENTITY)
            if climate_id:
                tasks.append(
                    self.hass.services.async_call(
                        CLIMATE_DOMAIN,
                        SERVICE_SET_HVAC_MODE,
                        {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: HVACMode.OFF},
                        blocking=False,
                    )
                )
        if tasks:
            await asyncio.gather(*tasks)
        self.eco_mode_active = False
        self.async_set_updated_data(self._calculate_all())

    async def async_smart_boost(
        self,
        room_id: str | None = None,
        temperature: float | None = None,
        duration_minutes: int | None = None,
    ) -> None:
        """Apply temporary boost temperature to one or all rooms."""
        target_temp = temperature if temperature is not None else self.smart_boost_temp
        duration_m = duration_minutes if duration_minutes is not None else self.smart_boost_duration
        duration_s = duration_m * 60

        target_rooms = [
            r for r in self.rooms_config
            if room_id is None or (r.get(CONF_ROOM_ID) or r.get(CONF_ROOM_NAME)) == room_id
        ]

        tasks = []
        for room in target_rooms:
            climate_id = room.get(CONF_ROOM_CLIMATE_ENTITY)
            rid = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME, "")
            if not climate_id:
                continue

            # Appliquer le boost
            tasks.append(
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_TEMPERATURE,
                    {ATTR_ENTITY_ID: climate_id, ATTR_TEMPERATURE: target_temp},
                    blocking=False,
                )
            )

            # Annuler l'éventuel timer existant
            if rid in self._boost_cancel_callbacks:
                self._boost_cancel_callbacks[rid]()
                del self._boost_cancel_callbacks[rid]

            # Planifier la reprise automatique
            target_dt = dt_util.utcnow() + timedelta(seconds=duration_s)

            @callback
            def _restore_callback(_now: datetime, c_id: str = climate_id, r_key: str = rid) -> None:
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        CLIMATE_DOMAIN,
                        SERVICE_SET_HVAC_MODE,
                        {ATTR_ENTITY_ID: c_id, ATTR_HVAC_MODE: HVACMode.AUTO},
                        blocking=False,
                    )
                )
                self._boost_cancel_callbacks.pop(r_key, None)

            self._boost_cancel_callbacks[rid] = async_track_point_in_time(
                self.hass, _restore_callback, target_dt
            )

        if tasks:
            await asyncio.gather(*tasks)

        self.async_set_updated_data(self._calculate_all())

    async def async_set_eco_mode(self, enabled: bool) -> None:
        """Enable or disable global Eco mode."""
        self.eco_mode_active = enabled

        if enabled:
            # Sauvegarder les états et appliquer la consigne éco
            tasks = []
            for room in self.rooms_config:
                climate_id = room.get(CONF_ROOM_CLIMATE_ENTITY)
                rid = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME, "")
                if not climate_id:
                    continue

                state = self.hass.states.get(climate_id)
                if state:
                    self._pre_eco_states[rid] = {
                        "mode": state.state,
                        "temp": state.attributes.get(ATTR_TEMPERATURE),
                    }

                tasks.append(
                    self.hass.services.async_call(
                        CLIMATE_DOMAIN,
                        SERVICE_SET_TEMPERATURE,
                        {ATTR_ENTITY_ID: climate_id, ATTR_TEMPERATURE: self.default_eco_temp},
                        blocking=False,
                    )
                )
            if tasks:
                await asyncio.gather(*tasks)
        else:
            # Reprise du planning auto partout
            await self.async_resume_all_schedules()

        self.async_set_updated_data(self._calculate_all())

    async def async_set_window_protection(self, enabled: bool) -> None:
        """Enable or disable window protection."""
        self.window_protection_enabled = enabled
        self.async_set_updated_data(self._calculate_all())

    async def async_set_adaptive_preheat(self, enabled: bool) -> None:
        """Enable or disable autonomous adaptive preheat."""
        self.preheat_autonomous_enabled = enabled
        self.async_set_updated_data(self._calculate_all())
