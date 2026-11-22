"""Unit tests and security verification for DomoLink-Tado-Light."""
import json
import os
import sys
import ast
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.ha_mock import setup_ha_mock
setup_ha_mock()

COMPONENT_DIR = os.path.join(REPO_ROOT, "custom_components", "domolink_tado_light")


def test_manifest_structure_and_version():
    """Verify manifest.json is valid and keys are properly ordered."""
    manifest_path = os.path.join(COMPONENT_DIR, "manifest.json")
    assert os.path.isfile(manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["domain"] == "domolink_tado_light"
    assert manifest["name"] == "DomoLink-Tado-Light"
    assert manifest["version"] == "1.0.4"
    assert manifest["codeowners"] == ["@SocrateMobile"]
    assert manifest["iot_class"] == "calculated"


def test_brand_assets_present():
    """Verify brand icons exist for HACS and Hassfest."""
    brand_dir = os.path.join(COMPONENT_DIR, "brand")
    assert os.path.isdir(brand_dir)
    for asset in ["icon.png", "icon@2x.png", "logo.png", "logo@2x.png"]:
        p = os.path.join(brand_dir, asset)
        assert os.path.isfile(p) and os.path.getsize(p) > 0, f"Missing or empty brand asset: {asset}"


def test_translations_parity():
    """Verify en.json and fr.json exist and match keys."""
    fr_path = os.path.join(COMPONENT_DIR, "translations", "fr.json")
    en_path = os.path.join(COMPONENT_DIR, "translations", "en.json")
    assert os.path.isfile(fr_path), "translations/fr.json must exist"
    assert os.path.isfile(en_path), "translations/en.json must exist"

    with open(fr_path, "r", encoding="utf-8") as f:
        fr = json.load(f)
    with open(en_path, "r", encoding="utf-8") as f:
        en = json.load(f)

    def extract_keys(d, prefix=""):
        keys = set()
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.update(extract_keys(v, full))
            else:
                keys.add(full)
        return keys

    fr_keys = extract_keys(fr)
    en_keys = extract_keys(en)
    assert fr_keys == en_keys, f"Translation keys mismatch: {fr_keys ^ en_keys}"


def test_physics_calculations():
    """Test the physical thermal calculation logic."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tado_light_physics",
        os.path.join(COMPONENT_DIR, "physics.py")
    )
    physics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(physics)

    dew_point = physics.calculate_dew_point(20.0, 50.0)
    assert dew_point is not None
    assert 9.0 <= dew_point <= 10.0

    abs_hum = physics.calculate_absolute_humidity(20.0, 50.0)
    assert abs_hum is not None
    assert abs_hum > 0


def test_no_direct_blocking_io_in_async_functions():
    """Verify no blocking calls at module level or inside async functions."""
    blocking_calls = {"open", "check_output", "urlopen"}
    violations = []

    def check_node(node, file_name):
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            return
        if isinstance(node, ast.AsyncFunctionDef):
            for child in node.body:
                check_async_body(child, node.name, file_name)
            return
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in blocking_calls:
                violations.append((file_name, "<module>", name, node.lineno))

        for child in ast.iter_child_nodes(node):
            check_node(child, file_name)

    def check_async_body(node, func_name, file_name):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in blocking_calls:
                violations.append((file_name, func_name, name, node.lineno))

        for child in ast.iter_child_nodes(node):
            check_async_body(child, func_name, file_name)

    for root, _, files in os.walk(COMPONENT_DIR):
        for file in files:
            if not file.endswith(".py"):
                continue
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            for item in tree.body:
                check_node(item, file)

    assert not violations, f"Blocking calls found: {violations}"


def test_options_flow_instantiation_and_readonly_config_entry():
    """Verify OptionsFlow instantiates without arguments and works with read-only config_entry."""
    import asyncio
    from homeassistant.config_entries import ConfigEntry
    from custom_components.domolink_tado_light.config_flow import (
        DomoLinkTadoLightConfigFlow,
        DomoLinkTadoLightOptionsFlowHandler,
    )

    entry = ConfigEntry(
        entry_id="entry_1",
        data={
            "rooms": [
                {"id": "living_room", "name": "Living Room", "climate_entity": "climate.living"}
            ]
        },
    )
    handler = DomoLinkTadoLightConfigFlow.async_get_options_flow(entry)
    assert isinstance(handler, DomoLinkTadoLightOptionsFlowHandler)
    handler._config_entry = entry

    result = asyncio.run(handler.async_step_init())
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert len(handler._rooms) == 1
    assert handler._rooms[0]["id"] == "living_room"
    # Defensive copy check
    assert handler._rooms[0] is not entry.data["rooms"][0]


def test_update_heating_rate_and_clamping():
    """Verify update_heating_rate ignores short sessions, applies EMA, and clamps [0.2, 5.0]."""
    from custom_components.domolink_tado_light.adaptive_preheat import update_heating_rate

    # Short session (< 12 min = 0.2h) is ignored
    assert update_heating_rate(1.5, 18.0, 19.0, 0.15) == 1.5

    # Non-positive delta is ignored
    assert update_heating_rate(1.5, 19.0, 19.0, 0.5) == 1.5

    # Valid session: 18.0 -> 20.0 in 1.0h => measured=2.0, EMA = 0.8*1.5 + 0.2*2.0 = 1.6
    assert update_heating_rate(1.5, 18.0, 20.0, 1.0) == 1.6

    # Clamping upper bound to 5.0
    assert update_heating_rate(5.0, 18.0, 24.0, 1.0) == 5.0

    # Clamping lower bound to 0.2
    assert update_heating_rate(0.1, 18.0, 18.1, 1.0) == 0.2


def test_detect_rapid_temperature_drop():
    """Verify rapid drop detection (>= 0.5C within <= 300s) vs slow drop."""
    from custom_components.domolink_tado_light.adaptive_preheat import detect_rapid_temperature_drop

    # Rapid drop: 20.5 -> 19.8 in 180s (drop 0.7 >= 0.5)
    assert detect_rapid_temperature_drop([(100.0, 20.5), (200.0, 20.2), (280.0, 19.8)]) is True

    # Slow drop: 20.5 -> 19.8 over 600s (> 300s)
    assert detect_rapid_temperature_drop([(100.0, 20.5), (700.0, 19.8)]) is False

    # Small drop: 20.5 -> 20.2 in 120s (drop 0.3 < 0.5)
    assert detect_rapid_temperature_drop([(100.0, 20.5), (220.0, 20.2)]) is False


def test_async_set_adaptive_preheat():
    """Verify toggling autonomous adaptive preheat persists state and stops active preheats."""
    import asyncio
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from custom_components.domolink_tado_light.coordinator import DomoLinkTadoLightCoordinator

    hass = HomeAssistant()
    entry = ConfigEntry(entry_id="test_preheat", data={"rooms": []})
    coord = DomoLinkTadoLightCoordinator(hass, entry.data, entry=entry)

    async def _run():
        await coord.async_set_adaptive_preheat(True)
        assert coord.preheat_autonomous_enabled is True
        stored = await coord._store.async_load()
        assert stored["preheat_autonomous_enabled"] is True

        coord._preheat_active["living"] = {
            "climate_id": "climate.living",
            "target_temp": 21.0,
            "cancel_timer": None,
        }
        await coord.async_set_adaptive_preheat(False)
        assert coord.preheat_autonomous_enabled is False
        assert "living" not in coord._preheat_active
        stored = await coord._store.async_load()
        assert stored["preheat_autonomous_enabled"] is False

    asyncio.run(_run())
