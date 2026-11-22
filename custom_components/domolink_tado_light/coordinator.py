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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_OPEN, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .adaptive_preheat import (
    detect_rapid_temperature_drop,
    estimate_preheat_duration,
    update_heating_rate,
)
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

    def __init__(
        self,
        hass: HomeAssistant,
        entry_data: dict[str, Any],
        entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
            config_entry=entry,
        )
        self.entry_data = entry_data
        self.rooms_config: list[dict[str, Any]] = entry_data.get(CONF_ROOMS, [])
        entry_id = entry.entry_id if entry is not None else entry_data.get("entry_id", "default")
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}_{entry_id}_state")

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

        # Apprentissage thermique, préchauffage autonome & détection de chute rapide
        self._learned_heating_rates: dict[str, float] = {}
        self._heating_sessions: dict[str, dict[str, float]] = {}
        self._preheat_active: dict[str, dict[str, Any]] = {}
        self._temp_history: dict[str, list[tuple[float, float]]] = {}
        self._thermal_window_cut_timers: dict[str, CALLBACK_TYPE] = {}

        # Suivi des timers de boost par pièce
        self._boost_cancel_callbacks: dict[str, CALLBACK_TYPE] = {}

        # Dictionnaire des écoutes d'états
        self._unsub_listeners: list[CALLBACK_TYPE] = []

    async def async_load_state(self) -> None:
        """Load persisted learned heating rates and adaptive preheat state."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            rates = stored.get("learned_heating_rates")
            if isinstance(rates, dict):
                self._learned_heating_rates = {
                    str(k): float(v)
                    for k, v in rates.items()
                    if isinstance(v, (int, float))
                }
            if "preheat_autonomous_enabled" in stored:
                self.preheat_autonomous_enabled = bool(stored["preheat_autonomous_enabled"])

    async def _async_save_state(self) -> None:
        """Persist learned heating rates and adaptive preheat state."""
        await self._store.async_save({
            "learned_heating_rates": self._learned_heating_rates,
            "preheat_autonomous_enabled": self.preheat_autonomous_enabled,
        })

    async def async_setup(self) -> None:
        """Set up entity listeners and initial state."""
        await self.async_load_state()
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

        for info in self._preheat_active.values():
            cancel_timer = info.get("cancel_timer")
            if cancel_timer:
                cancel_timer()
        self._preheat_active.clear()

        for cancel in self._thermal_window_cut_timers.values():
            cancel()
        self._thermal_window_cut_timers.clear()

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
        now = time.monotonic()
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
            configured_rate = float(room.get(CONF_HEATING_RATE, DEFAULT_HEATING_RATE))
            is_learned = room_id in self._learned_heating_rates
            heating_rate = self._learned_heating_rates.get(room_id, configured_rate)

            climate_state = self.hass.states.get(climate_id) if climate_id else None

            # Température cible & actuelle depuis l'entité climate
            target_temp: float | None = None
            climate_current_temp: float | None = None
            hvac_mode: str | None = None
            hvac_action: str | None = None

            if climate_state:
                hvac_mode = climate_state.state
                attrs = climate_state.attributes
                target_temp = attrs.get(ATTR_TEMPERATURE)
                climate_current_temp = attrs.get(ATTR_CURRENT_TEMPERATURE)
                hvac_action = attrs.get("hvac_action")

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

            # État de la fenêtre & historique thermique glissant (600s)
            window_open = self._get_bool_state(window_id)
            if indoor_temp is not None:
                total_indoor_temp += indoor_temp
                indoor_temp_count += 1
                history = self._temp_history.setdefault(room_id, [])
                history.append((now, indoor_temp))
                self._temp_history[room_id] = [
                    (ts, t) for ts, t in history if now - ts <= 600.0
                ]

            rapid_drop = detect_rapid_temperature_drop(self._temp_history.get(room_id, []))

            # Détection pièce en chauffe
            is_heating = (hvac_action == "heating") or (
                hvac_mode == HVACMode.HEAT and temp_delta is not None and temp_delta > 0.3
            )
            if hvac_mode == HVACMode.HEAT or (hvac_mode == HVACMode.AUTO and temp_delta and temp_delta > 0.2):
                active_heating_rooms += 1

            # Apprentissage réel de l'inertie thermique (sessions >= 12 min)
            if window_open or hvac_mode == HVACMode.OFF:
                self._heating_sessions.pop(room_id, None)
            elif indoor_temp is not None and target_temp is not None:
                if room_id not in self._heating_sessions:
                    if is_heating and temp_delta is not None and temp_delta > 0.3:
                        self._heating_sessions[room_id] = {
                            "start_time": now,
                            "start_temp": indoor_temp,
                            "target_temp": target_temp,
                        }
                else:
                    session = self._heating_sessions[room_id]
                    if indoor_temp >= target_temp - 0.1 or not is_heating:
                        duration_hours = (now - session["start_time"]) / 3600.0
                        start_temp = session["start_temp"]
                        self._heating_sessions.pop(room_id, None)
                        if duration_hours >= 0.2 and indoor_temp > start_temp:
                            heating_rate = update_heating_rate(
                                heating_rate, start_temp, indoor_temp, duration_hours
                            )
                            self._learned_heating_rates[room_id] = heating_rate
                            is_learned = True
                            self.hass.async_create_task(self._async_save_state())

            # Préchauffage estimé avec taux appris
            preheat_duration = estimate_preheat_duration(target_temp, indoor_temp, heating_rate)

            # Gestion automatique de coupure sur fenêtre ouverte ou chute rapide de température
            if self.window_protection_enabled and climate_id:
                if (
                    (window_open or rapid_drop)
                    and room_id not in self._window_cut_states
                    and hvac_mode != HVACMode.OFF
                ):
                    reason = "window" if window_open else "thermal_drop"
                    self._window_cut_states[room_id] = {
                        "mode": hvac_mode or HVACMode.AUTO,
                        "temp": target_temp,
                        "reason": reason,
                    }
                    self.hass.async_create_task(
                        self._async_handle_window_cut(room_id, climate_id, reason)
                    )
                elif room_id in self._window_cut_states:
                    cut_info = self._window_cut_states[room_id]
                    reason = cut_info.get("reason", "window")
                    hist = self._temp_history.get(room_id, [])
                    temp_rising = len(hist) >= 2 and (hist[-1][1] - hist[-2][1]) >= 0.1
                    if (reason == "window" and not window_open) or (
                        reason == "thermal_drop" and temp_rising
                    ):
                        saved = self._window_cut_states.pop(room_id, None)
                        cancel_thermal = self._thermal_window_cut_timers.pop(room_id, None)
                        if cancel_thermal:
                            cancel_thermal()
                        if saved:
                            self.hass.async_create_task(
                                self._async_restore_window_cut(room_id, climate_id, saved)
                            )

            # Préchauffage autonome actif
            if (
                self.preheat_autonomous_enabled
                and not self.eco_mode_active
                and not window_open
                and room_id not in self._window_cut_states
            ):
                if (
                    climate_id
                    and target_temp is not None
                    and temp_delta is not None
                    and temp_delta >= 0.5
                    and preheat_duration > 0
                    and not is_heating
                    and hvac_mode not in (HVACMode.HEAT, HVACMode.OFF)
                    and room_id not in self._preheat_active
                ):
                    self._preheat_active[room_id] = {
                        "climate_id": climate_id,
                        "target_temp": target_temp,
                        "cancel_timer": None,
                    }
                    self.hass.async_create_task(
                        self._async_start_autonomous_preheat(
                            room_id, climate_id, target_temp, preheat_duration
                        )
                    )

            if room_id in self._preheat_active and (
                window_open
                or self.eco_mode_active
                or room_id in self._window_cut_states
                or (
                    indoor_temp is not None
                    and target_temp is not None
                    and indoor_temp >= target_temp - 0.1
                )
            ):
                preheat_info = self._preheat_active.pop(room_id, None)
                if preheat_info:
                    cancel_timer = preheat_info.get("cancel_timer")
                    if cancel_timer:
                        cancel_timer()
                    self.hass.async_create_task(
                        self._async_stop_autonomous_preheat(room_id, preheat_info)
                    )

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
                "preheat_active": room_id in self._preheat_active,
                "heating_rate": heating_rate,
                "configured_rate": configured_rate,
                "is_learned": is_learned,
                "window_open": window_open,
                "rapid_drop_detected": rapid_drop,
                "window_cut_active": room_id in self._window_cut_states,
            }

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
        self, room_id: str, climate_id: str, reason: str = "window"
    ) -> None:
        """Turn off climate when window opens or rapid temperature drop is detected."""
        _LOGGER.info(
            "Protection fenêtre (%s) déclenchée dans %s: mise hors-gel de %s",
            reason,
            room_id,
            climate_id,
        )
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: HVACMode.OFF},
            blocking=False,
        )
        if reason == "thermal_drop":
            old_cancel = self._thermal_window_cut_timers.pop(room_id, None)
            if old_cancel:
                old_cancel()
            restore_dt = dt_util.utcnow() + timedelta(minutes=15)

            @callback
            def _auto_restore_cb(
                _now: datetime, r_key: str = room_id, c_id: str = climate_id
            ) -> None:
                self._thermal_window_cut_timers.pop(r_key, None)
                saved = self._window_cut_states.pop(r_key, None)
                if saved:
                    self.hass.async_create_task(
                        self._async_restore_window_cut(r_key, c_id, saved)
                    )

            self._thermal_window_cut_timers[room_id] = async_track_point_in_time(
                self.hass, _auto_restore_cb, restore_dt
            )

    async def _async_restore_window_cut(
        self,
        room_id: str,
        climate_id: str,
        saved: dict[str, Any] | None = None,
    ) -> None:
        """Restore climate state when window closes."""
        if saved is None:
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

    async def _async_start_autonomous_preheat(
        self,
        room_id: str,
        climate_id: str,
        target_temp: float,
        preheat_duration: int,
    ) -> None:
        """Start autonomous preheating and arm a safety timer."""
        _LOGGER.info(
            "Préchauffage autonome démarré dans %s (%s -> %.1f°C, max %d min)",
            room_id,
            climate_id,
            target_temp,
            preheat_duration,
        )
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: HVACMode.HEAT},
            blocking=False,
        )
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: climate_id, ATTR_TEMPERATURE: target_temp},
            blocking=False,
        )

        if room_id in self._preheat_active:
            stop_dt = dt_util.utcnow() + timedelta(minutes=max(1, preheat_duration))

            @callback
            def _safety_stop_cb(_now: datetime, r_key: str = room_id) -> None:
                info = self._preheat_active.pop(r_key, None)
                if info:
                    self.hass.async_create_task(
                        self._async_stop_autonomous_preheat(r_key, info)
                    )

            self._preheat_active[room_id]["cancel_timer"] = async_track_point_in_time(
                self.hass, _safety_stop_cb, stop_dt
            )

    async def _async_stop_autonomous_preheat(
        self,
        room_id: str,
        info: dict[str, Any] | None = None,
    ) -> None:
        """Stop autonomous preheating and restore AUTO schedule."""
        if info is None:
            info = self._preheat_active.pop(room_id, None)
        if not info:
            return
        cancel_timer = info.get("cancel_timer")
        if cancel_timer:
            cancel_timer()
        climate_id = info.get("climate_id")
        if climate_id:
            _LOGGER.info("Préchauffage autonome terminé dans %s: retour en mode AUTO sur %s", room_id, climate_id)
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_HVAC_MODE,
                {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: HVACMode.AUTO},
                blocking=False,
            )

    # =========================================================================
    # ACTIONS GLOBALES ET SERVICE CALLS (TADO OFFICIEL -> FALLBACK DOMOLINK)
    # =========================================================================

    def _has_official_tado(self) -> bool:
        """Test presence of official Tado integration."""
        if "tado" in self.hass.config.components:
            return True
        if self.hass.config_entries.async_entries("tado"):
            return True
        return False

    def _has_domolink_tado(self) -> bool:
        """Test presence of DomoLink-Tado integration (fallback)."""
        if "domolink_tado" in self.hass.config.components:
            return True
        if self.hass.config_entries.async_entries("domolink_tado"):
            return True
        return False

    async def async_resume_all_schedules(self) -> None:
        """Resume schedule (AUTO mode) across all configured climate entities.
        Prioritizes official Tado climate modes, with fallback to DomoLink-Tado bulk services.
        """
        # 1. Test présence Tado officiel
        if self._has_official_tado():
            _LOGGER.debug("Reprise plannings via Tado officiel (climate.set_hvac_mode auto)")
            tasks = [
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_HVAC_MODE,
                    {ATTR_ENTITY_ID: room[CONF_ROOM_CLIMATE_ENTITY], ATTR_HVAC_MODE: HVACMode.AUTO},
                    blocking=False,
                )
                for room in self.rooms_config
                if room.get(CONF_ROOM_CLIMATE_ENTITY)
            ]
            if tasks:
                await asyncio.gather(*tasks)

        # 2. En fallback, passage sur DomoLink-Tado
        elif self._has_domolink_tado() and self.hass.services.has_service("domolink_tado", "resume_all_schedules"):
            _LOGGER.debug("Reprise plannings via DomoLink-Tado (domolink_tado.resume_all_schedules)")
            await self.hass.services.async_call("domolink_tado", "resume_all_schedules", blocking=False)

        # 3. Fallback standard sur toutes les entités configurées
        else:
            tasks = [
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_HVAC_MODE,
                    {ATTR_ENTITY_ID: room[CONF_ROOM_CLIMATE_ENTITY], ATTR_HVAC_MODE: HVACMode.AUTO},
                    blocking=False,
                )
                for room in self.rooms_config
                if room.get(CONF_ROOM_CLIMATE_ENTITY)
            ]
            if tasks:
                await asyncio.gather(*tasks)

        self._pre_eco_states.clear()
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
        """Turn off (frost protection) all configured climate entities.
        Prioritizes official Tado climate modes, with fallback to DomoLink-Tado bulk services.
        """
        # 1. Test présence Tado officiel
        if self._has_official_tado():
            _LOGGER.debug("Mise hors-gel via Tado officiel (climate.set_hvac_mode off)")
            tasks = [
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_HVAC_MODE,
                    {ATTR_ENTITY_ID: room[CONF_ROOM_CLIMATE_ENTITY], ATTR_HVAC_MODE: HVACMode.OFF},
                    blocking=False,
                )
                for room in self.rooms_config
                if room.get(CONF_ROOM_CLIMATE_ENTITY)
            ]
            if tasks:
                await asyncio.gather(*tasks)

        # 2. En fallback, passage sur DomoLink-Tado
        elif self._has_domolink_tado() and self.hass.services.has_service("domolink_tado", "set_all_off"):
            _LOGGER.debug("Mise hors-gel via DomoLink-Tado (domolink_tado.set_all_off)")
            await self.hass.services.async_call("domolink_tado", "set_all_off", blocking=False)

        # 3. Fallback standard
        else:
            tasks = [
                self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_HVAC_MODE,
                    {ATTR_ENTITY_ID: room[CONF_ROOM_CLIMATE_ENTITY], ATTR_HVAC_MODE: HVACMode.OFF},
                    blocking=False,
                )
                for room in self.rooms_config
                if room.get(CONF_ROOM_CLIMATE_ENTITY)
            ]
            if tasks:
                await asyncio.gather(*tasks)

        self._pre_eco_states.clear()
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
        """Enable or disable global Eco mode: test official Tado first, then DomoLink-Tado as fallback."""
        self.eco_mode_active = enabled

        if enabled:
            # 1. Test présence Tado officiel
            if self._has_official_tado():
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

            # 2. En fallback, passage sur DomoLink-Tado
            elif self._has_domolink_tado() and self.hass.services.has_service("domolink_tado", "set_eco_all"):
                await self.hass.services.async_call(
                    "domolink_tado",
                    "set_eco_all",
                    {"temperature": self.default_eco_temp},
                    blocking=False,
                )

            # 3. Fallback standard
            else:
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
            if self._pre_eco_states:
                restore_tasks = []
                for room in self.rooms_config:
                    climate_id = room.get(CONF_ROOM_CLIMATE_ENTITY)
                    rid = room.get(CONF_ROOM_ID) or room.get(CONF_ROOM_NAME, "")
                    if not climate_id:
                        continue
                    saved = self._pre_eco_states.get(rid)
                    target_mode = (saved or {}).get("mode")
                    if not target_mode or target_mode in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                        target_mode = HVACMode.AUTO
                    restore_tasks.append(
                        self.hass.services.async_call(
                            CLIMATE_DOMAIN,
                            SERVICE_SET_HVAC_MODE,
                            {ATTR_ENTITY_ID: climate_id, ATTR_HVAC_MODE: target_mode},
                            blocking=False,
                        )
                    )
                    saved_temp = (saved or {}).get("temp")
                    if saved_temp is not None and target_mode not in (HVACMode.OFF, HVACMode.AUTO):
                        restore_tasks.append(
                            self.hass.services.async_call(
                                CLIMATE_DOMAIN,
                                SERVICE_SET_TEMPERATURE,
                                {ATTR_ENTITY_ID: climate_id, ATTR_TEMPERATURE: saved_temp},
                                blocking=False,
                            )
                        )
                if restore_tasks:
                    await asyncio.gather(*restore_tasks)
                self._pre_eco_states.clear()
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
        if not enabled:
            for rid in list(self._preheat_active):
                info = self._preheat_active.pop(rid, None)
                await self._async_stop_autonomous_preheat(rid, info)
        await self._async_save_state()
        self.async_set_updated_data(self._calculate_all())
