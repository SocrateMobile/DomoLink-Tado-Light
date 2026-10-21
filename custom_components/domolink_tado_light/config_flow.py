"""Config flow and Options flow for DomoLink-Tado-Light."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er, selector

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
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)


class DomoLinkTadoLightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DomoLink-Tado-Light."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._entry_data: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []
        self._detected_rooms: list[tuple[str, str]] = []
        self._detected_source: str = ""

    def _detect_tado_climates(self) -> tuple[str, list[tuple[str, str]]]:
        """Detect climate entities: tests official Tado first, then DomoLink-Tado as fallback."""
        ent_reg = er.async_get(self.hass)

        # 1. Test présence Tado officiel
        official_tado = [
            entry for entry in ent_reg.entities.values()
            if entry.domain == CLIMATE_DOMAIN and entry.platform == "tado" and not entry.disabled
        ]
        if official_tado:
            rooms = [
                (
                    entry.name or entry.original_name or entry.entity_id.replace("climate.", "").replace("_", " ").title(),
                    entry.entity_id
                )
                for entry in official_tado
            ]
            _LOGGER.info("DomoLink-Tado-Light: Détection de %d thermostat(s) Tado officiel", len(rooms))
            return ("Tado Officiel", rooms)

        # 2. En fallback, test présence DomoLink-Tado
        domolink_tado = [
            entry for entry in ent_reg.entities.values()
            if entry.domain == CLIMATE_DOMAIN and entry.platform == "domolink_tado" and not entry.disabled
        ]
        if domolink_tado:
            rooms = [
                (
                    entry.name or entry.original_name or entry.entity_id.replace("climate.", "").replace("_", " ").title(),
                    entry.entity_id
                )
                for entry in domolink_tado
            ]
            _LOGGER.info("DomoLink-Tado-Light: Détection de %d thermostat(s) DomoLink-Tado (fallback)", len(rooms))
            return ("DomoLink-Tado", rooms)

        # 3. Fallback générique par recherche d'entités contenant "tado"
        all_climates = self.hass.states.async_entity_ids(CLIMATE_DOMAIN)
        tado_by_name = [c for c in all_climates if "tado" in c.lower()]
        if tado_by_name:
            rooms = []
            for c in tado_by_name:
                state = self.hass.states.get(c)
                name = (state.attributes.get("friendly_name") if state else None) or c.replace("climate.", "").replace("_", " ").title()
                rooms.append((name, c))
            return ("Tado (entités détectées)", rooms)

        return ("", [])

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        # S'assurer qu'une seule instance globale existe
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            self._entry_data = {
                CONF_OUTDOOR_TEMP_ENTITY: user_input.get(CONF_OUTDOOR_TEMP_ENTITY),
                CONF_OUTDOOR_HUMIDITY_ENTITY: user_input.get(CONF_OUTDOOR_HUMIDITY_ENTITY),
                CONF_DEFAULT_ECO_TEMP: user_input.get(CONF_DEFAULT_ECO_TEMP, DEFAULT_ECO_TEMP),
                CONF_SMART_BOOST_TEMP: user_input.get(CONF_SMART_BOOST_TEMP, DEFAULT_SMART_BOOST_TEMP),
                CONF_SMART_BOOST_DURATION: user_input.get(CONF_SMART_BOOST_DURATION, DEFAULT_SMART_BOOST_DURATION),
                CONF_ROOMS: [],
            }
            source, detected = self._detect_tado_climates()
            if detected:
                self._detected_rooms = detected
                self._detected_source = source
                return await self.async_step_auto_detect()

            return await self.async_step_add_room()

        schema = vol.Schema({
            vol.Optional(CONF_OUTDOOR_TEMP_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE)
            ),
            vol.Optional(CONF_OUTDOOR_HUMIDITY_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.HUMIDITY)
            ),
            vol.Optional(CONF_DEFAULT_ECO_TEMP, default=DEFAULT_ECO_TEMP): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5.0, max=25.0, step=0.5, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_SMART_BOOST_TEMP, default=DEFAULT_SMART_BOOST_TEMP): selector.NumberSelector(
                selector.NumberSelectorConfig(min=18.0, max=30.0, step=0.5, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_SMART_BOOST_DURATION, default=DEFAULT_SMART_BOOST_DURATION): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=180, step=5, unit_of_measurement="min")
            ),
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_auto_detect(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step to confirm auto-detected rooms from Tado official or DomoLink-Tado."""
        if user_input is not None:
            if user_input.get("use_auto_detected", True):
                selected_entities = user_input.get("selected_rooms", [c for _, c in self._detected_rooms])
                for name, climate_id in self._detected_rooms:
                    if climate_id in selected_entities:
                        room_id = name.lower().replace(" ", "_")
                        self._rooms.append({
                            CONF_ROOM_ID: room_id,
                            CONF_ROOM_NAME: name,
                            CONF_ROOM_CLIMATE_ENTITY: climate_id,
                            CONF_ROOM_TEMP_ENTITY: None,
                            CONF_ROOM_HUMIDITY_ENTITY: None,
                            CONF_ROOM_WINDOW_ENTITY: None,
                            CONF_HEATING_RATE: DEFAULT_HEATING_RATE,
                        })
                self._entry_data[CONF_ROOMS] = self._rooms
                return self.async_create_entry(title=NAME, data=self._entry_data)

            return await self.async_step_add_room()

        options = [
            selector.SelectOptionDict(value=c, label=f"{name} ({c})")
            for name, c in self._detected_rooms
        ]
        schema = vol.Schema({
            vol.Required("use_auto_detected", default=True): selector.BooleanSelector(),
            vol.Optional("selected_rooms", default=[c for _, c in self._detected_rooms]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })

        return self.async_show_form(
            step_id="auto_detect",
            data_schema=schema,
            description_placeholders={
                "source": self._detected_source,
                "count": str(len(self._detected_rooms)),
            },
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a room / zone to the configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            action = user_input.get("action")
            if action == "finish":
                self._entry_data[CONF_ROOMS] = self._rooms
                return self.async_create_entry(title=NAME, data=self._entry_data)

            # Enregistrer la pièce
            room_name = user_input[CONF_ROOM_NAME].strip()
            room_id = room_name.lower().replace(" ", "_")
            self._rooms.append({
                CONF_ROOM_ID: room_id,
                CONF_ROOM_NAME: room_name,
                CONF_ROOM_CLIMATE_ENTITY: user_input.get(CONF_ROOM_CLIMATE_ENTITY),
                CONF_ROOM_TEMP_ENTITY: user_input.get(CONF_ROOM_TEMP_ENTITY),
                CONF_ROOM_HUMIDITY_ENTITY: user_input.get(CONF_ROOM_HUMIDITY_ENTITY),
                CONF_ROOM_WINDOW_ENTITY: user_input.get(CONF_ROOM_WINDOW_ENTITY),
                CONF_HEATING_RATE: user_input.get(CONF_HEATING_RATE, DEFAULT_HEATING_RATE),
            })

            # Proposer d'ajouter une autre pièce
            return await self.async_step_add_room()

        schema = vol.Schema({
            vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
            vol.Required(CONF_ROOM_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
            ),
            vol.Optional(CONF_ROOM_TEMP_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE)
            ),
            vol.Optional(CONF_ROOM_HUMIDITY_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.HUMIDITY)
            ),
            vol.Optional(CONF_ROOM_WINDOW_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
            ),
            vol.Optional(CONF_HEATING_RATE, default=DEFAULT_HEATING_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.2, max=5.0, step=0.1, unit_of_measurement="°C/h")
            ),
            vol.Optional("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="add", label="Enregistrer et ajouter une autre pièce"),
                        selector.SelectOptionDict(value="finish", label="Terminer la configuration"),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })

        return self.async_show_form(
            step_id="add_room",
            data_schema=schema,
            errors=errors,
            description_placeholders={"rooms_count": str(len(self._rooms))},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return DomoLinkTadoLightOptionsFlowHandler(config_entry)


class DomoLinkTadoLightOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for DomoLink-Tado-Light."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self._rooms: list[dict[str, Any]] = list(
            config_entry.options.get(CONF_ROOMS, config_entry.data.get(CONF_ROOMS, []))
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage main options menu."""
        if user_input is not None:
            choice = user_input.get("choice")
            if choice == "general":
                return await self.async_step_general()
            if choice == "add_room":
                return await self.async_step_add_room()
            if choice == "remove_room":
                return await self.async_step_remove_room()

        options = [
            selector.SelectOptionDict(value="general", label="Paramètres généraux (Éco, Boost, Météo)"),
            selector.SelectOptionDict(value="add_room", label="Ajouter une nouvelle pièce"),
        ]
        if self._rooms:
            options.append(selector.SelectOptionDict(value="remove_room", label="Supprimer une pièce"))

        schema = vol.Schema({
            vol.Required("choice", default="general"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST)
            )
        })
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit general settings."""
        current_data = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            new_options = {**self.config_entry.options, **user_input, CONF_ROOMS: self._rooms}
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema({
            vol.Optional(
                CONF_OUTDOOR_TEMP_ENTITY,
                default=current_data.get(CONF_OUTDOOR_TEMP_ENTITY),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE)
            ),
            vol.Optional(
                CONF_OUTDOOR_HUMIDITY_ENTITY,
                default=current_data.get(CONF_OUTDOOR_HUMIDITY_ENTITY),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.HUMIDITY)
            ),
            vol.Optional(
                CONF_DEFAULT_ECO_TEMP,
                default=current_data.get(CONF_DEFAULT_ECO_TEMP, DEFAULT_ECO_TEMP),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5.0, max=25.0, step=0.5, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_SMART_BOOST_TEMP,
                default=current_data.get(CONF_SMART_BOOST_TEMP, DEFAULT_SMART_BOOST_TEMP),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=18.0, max=30.0, step=0.5, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_SMART_BOOST_DURATION,
                default=current_data.get(CONF_SMART_BOOST_DURATION, DEFAULT_SMART_BOOST_DURATION),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=180, step=5, unit_of_measurement="min")
            ),
        })
        return self.async_show_form(step_id="general", data_schema=schema)

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a room via options flow."""
        if user_input is not None:
            room_name = user_input[CONF_ROOM_NAME].strip()
            room_id = room_name.lower().replace(" ", "_")
            self._rooms.append({
                CONF_ROOM_ID: room_id,
                CONF_ROOM_NAME: room_name,
                CONF_ROOM_CLIMATE_ENTITY: user_input.get(CONF_ROOM_CLIMATE_ENTITY),
                CONF_ROOM_TEMP_ENTITY: user_input.get(CONF_ROOM_TEMP_ENTITY),
                CONF_ROOM_HUMIDITY_ENTITY: user_input.get(CONF_ROOM_HUMIDITY_ENTITY),
                CONF_ROOM_WINDOW_ENTITY: user_input.get(CONF_ROOM_WINDOW_ENTITY),
                CONF_HEATING_RATE: user_input.get(CONF_HEATING_RATE, DEFAULT_HEATING_RATE),
            })
            new_options = {**self.config_entry.options, CONF_ROOMS: self._rooms}
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema({
            vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
            vol.Required(CONF_ROOM_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
            ),
            vol.Optional(CONF_ROOM_TEMP_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE)
            ),
            vol.Optional(CONF_ROOM_HUMIDITY_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.HUMIDITY)
            ),
            vol.Optional(CONF_ROOM_WINDOW_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
            ),
            vol.Optional(CONF_HEATING_RATE, default=DEFAULT_HEATING_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.2, max=5.0, step=0.1, unit_of_measurement="°C/h")
            ),
        })
        return self.async_show_form(step_id="add_room", data_schema=schema)

    async def async_step_remove_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove a room from options."""
        if user_input is not None:
            to_remove = user_input.get("room_to_remove")
            self._rooms = [
                r for r in self._rooms
                if (r.get(CONF_ROOM_ID) or r.get(CONF_ROOM_NAME)) != to_remove
            ]
            new_options = {**self.config_entry.options, CONF_ROOMS: self._rooms}
            return self.async_create_entry(title="", data=new_options)

        room_options = [
            selector.SelectOptionDict(
                value=r.get(CONF_ROOM_ID) or r.get(CONF_ROOM_NAME, ""),
                label=r.get(CONF_ROOM_NAME, "Inconnu"),
            )
            for r in self._rooms
        ]
        schema = vol.Schema({
            vol.Required("room_to_remove"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=room_options, mode=selector.SelectSelectorMode.LIST)
            )
        })
        return self.async_show_form(step_id="remove_room", data_schema=schema)
