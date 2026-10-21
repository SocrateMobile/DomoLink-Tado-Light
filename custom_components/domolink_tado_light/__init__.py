"""Initialization for DomoLink-Tado-Light."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .coordinator import DomoLinkTadoLightCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_RESUME_ALL = "resume_all_schedules"
SERVICE_TURN_OFF_ALL = "turn_off_all"
SERVICE_SMART_BOOST = "smart_boost"
SERVICE_SET_ECO_MODE = "set_eco_mode"

SCHEMA_SMART_BOOST = vol.Schema({
    vol.Optional("room_id"): cv.string,
    vol.Optional("temperature"): vol.Coerce(float),
    vol.Optional("duration_minutes"): vol.Coerce(int),
})

SCHEMA_SET_ECO_MODE = vol.Schema({
    vol.Required("enabled"): cv.boolean,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DomoLink-Tado-Light from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    combined_data = {**entry.data, **entry.options}
    coordinator = DomoLinkTadoLightCoordinator(hass, combined_data)

    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Enregistrement des services Home Assistant
    async def handle_resume_all(call: ServiceCall) -> None:
        await coordinator.async_resume_all_schedules()

    async def handle_turn_off_all(call: ServiceCall) -> None:
        await coordinator.async_turn_off_all()

    async def handle_smart_boost(call: ServiceCall) -> None:
        room_id = call.data.get("room_id")
        temp = call.data.get("temperature")
        dur = call.data.get("duration_minutes")
        await coordinator.async_smart_boost(room_id, temp, dur)

    async def handle_set_eco(call: ServiceCall) -> None:
        enabled = call.data.get("enabled", True)
        await coordinator.async_set_eco_mode(enabled)

    hass.services.async_register(DOMAIN, SERVICE_RESUME_ALL, handle_resume_all)
    hass.services.async_register(DOMAIN, SERVICE_TURN_OFF_ALL, handle_turn_off_all)
    hass.services.async_register(DOMAIN, SERVICE_SMART_BOOST, handle_smart_boost, schema=SCHEMA_SMART_BOOST)
    hass.services.async_register(DOMAIN, SERVICE_SET_ECO_MODE, handle_set_eco, schema=SCHEMA_SET_ECO_MODE)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: DomoLinkTadoLightCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_unload()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry after options change."""
    await hass.config_entries.async_reload(entry.entry_id)
