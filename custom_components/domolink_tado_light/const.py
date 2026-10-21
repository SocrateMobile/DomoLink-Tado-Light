"""Constants for DomoLink-Tado-Light."""
from __future__ import annotations

import json
import os
from homeassistant.const import Platform

DOMAIN = "domolink_tado_light"
NAME = "DomoLink-Tado-Light"

# Lecture dynamique de la version depuis manifest.json
_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "manifest.json")
try:
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as _f:
        VERSION = json.load(_f).get("version", "1.0.0")
except Exception:
    VERSION = "1.0.0"

# Configuration Entry keys
CONF_OUTDOOR_TEMP_ENTITY = "outdoor_temp_entity"
CONF_OUTDOOR_HUMIDITY_ENTITY = "outdoor_humidity_entity"
CONF_DEFAULT_ECO_TEMP = "default_eco_temp"
CONF_SMART_BOOST_TEMP = "smart_boost_temp"
CONF_SMART_BOOST_DURATION = "smart_boost_duration"
CONF_ROOMS = "rooms"

# Room keys
CONF_ROOM_ID = "id"
CONF_ROOM_NAME = "name"
CONF_ROOM_CLIMATE_ENTITY = "climate_entity"
CONF_ROOM_TEMP_ENTITY = "temp_entity"
CONF_ROOM_HUMIDITY_ENTITY = "humidity_entity"
CONF_ROOM_WINDOW_ENTITY = "window_entity"
CONF_HEATING_RATE = "heating_rate"

# Aliases de compatibilité
CONF_CLIMATE_ENTITY = CONF_ROOM_CLIMATE_ENTITY
CONF_TEMP_ENTITY = CONF_ROOM_TEMP_ENTITY
CONF_HUMIDITY_ENTITY = CONF_ROOM_HUMIDITY_ENTITY
CONF_WINDOW_ENTITY = CONF_ROOM_WINDOW_ENTITY

# Valeurs par défaut
DEFAULT_ECO_TEMP = 17.0
DEFAULT_SMART_BOOST_TEMP = 21.5
DEFAULT_SMART_BOOST_DURATION = 30  # minutes
DEFAULT_HEATING_RATE = 1.5  # °C/h
DEFAULT_UPDATE_INTERVAL = 30  # secondes

# Limites de températures
MIN_TEMP = 5.0
MAX_TEMP = 30.0
TEMP_STEP = 0.5

# Plateformes supportées
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
]
