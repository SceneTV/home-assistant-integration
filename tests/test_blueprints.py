"""Check that every shipped blueprint loads and builds a valid automation."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import pytest

from homeassistant.components import automation
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

# Importing the package first makes ``custom_components`` resolve to this repo
# rather than the test harness's own testing_config/custom_components.
from custom_components.android_tv_bridge.const import DOMAIN
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

BLUEPRINT_DIR = (
    Path(__file__).parent.parent / "blueprints" / "automation" / "android_tv_bridge"
)

DEVICE = "__device__"

INPUTS: dict[str, dict[str, Any]] = {
    "movie_mode.yaml": {
        "tv": DEVICE,
        "lights": ["light.living_room"],
        "apps": ["com.plexapp.android"],
    },
    "doorbell_popup.yaml": {
        "doorbell": "binary_sensor.doorbell",
        "camera": "camera.front_door",
        "tv": DEVICE,
        "ha_url": "http://192.168.1.10:8123",
    },
    "presence_profile.yaml": {
        "person": "person.tyler",
        "profile_select": "select.living_room_tv_active_profile",
        "arrive_profile": "Tyler",
    },
    "bedtime_lock.yaml": {
        "tv": DEVICE,
        "profile_select": "select.living_room_tv_active_profile",
        "home_button": "button.living_room_tv_home",
        "kids_profile": "Kids",
    },
    "lights_off_when_idle.yaml": {
        "tv": DEVICE,
        "playing_sensor": "binary_sensor.living_room_tv_playing",
        "lights": ["light.living_room"],
    },
}


def test_every_blueprint_has_test_inputs() -> None:
    assert {p.name for p in BLUEPRINT_DIR.glob("*.yaml")} == set(INPUTS)


@pytest.mark.parametrize("filename", sorted(INPUTS))
async def test_blueprint_builds_valid_automation(
    hass: HomeAssistant, filename: str, request: pytest.FixtureRequest
) -> None:
    target = Path(hass.config.path("blueprints", "automation", DOMAIN))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT_DIR / filename, target / filename)
    request.addfinalizer(lambda: shutil.rmtree(target, ignore_errors=True))

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="launcher-1",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "launcher-1")}
    )
    inputs = {
        key: device.id if value == DEVICE else value
        for key, value in INPUTS[filename].items()
    }

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "id": "under_test",
                "alias": "Under test",
                "use_blueprint": {
                    "path": f"android_tv_bridge/{filename}",
                    "input": inputs,
                },
            }
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("automation.under_test")
    assert state is not None, "automation was not created"
    # An invalid blueprint or automation config leaves the entity unavailable.
    assert state.state == "on", state.attributes


async def test_movie_mode_dims_lights_on_playback(
    hass: HomeAssistant, request: pytest.FixtureRequest
) -> None:
    """End to end: a launcher media_started event runs the blueprint's actions."""
    target = Path(hass.config.path("blueprints", "automation", DOMAIN))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT_DIR / "movie_mode.yaml", target / "movie_mode.yaml")
    request.addfinalizer(lambda: shutil.rmtree(target, ignore_errors=True))

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="launcher-1",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "launcher-1")}
    )
    scene_create = async_mock_service(hass, "scene", "create")
    light_off = async_mock_service(hass, "light", "turn_off")

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "id": "movie",
                "use_blueprint": {
                    "path": f"{DOMAIN}/movie_mode.yaml",
                    "input": {
                        "tv": device.id,
                        "lights": ["light.living_room"],
                        "apps": ["com.plexapp.android"],
                    },
                },
            }
        },
    )
    await hass.async_block_till_done()

    def fire(package: str) -> None:
        hass.bus.async_fire(
            f"{DOMAIN}.media_started",
            {"device_id": "launcher-1", "media": {"package": package}},
        )

    fire("com.google.android.youtube.tv")  # not in the app list
    await hass.async_block_till_done()
    assert light_off == []

    fire("com.plexapp.android")
    await hass.async_block_till_done()
    assert len(scene_create) == 1
    assert scene_create[0].data["snapshot_entities"] == ["light.living_room"]
    assert len(light_off) == 1
    assert light_off[0].data["entity_id"] == ["light.living_room"]
