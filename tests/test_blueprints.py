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
    "announce_on_tv.yaml": {
        "announce_trigger": [
            {"trigger": "state", "entity_id": "lock.front_door", "to": "unlocked"}
        ],
        "message": "Front door unlocked",
        "tts_engine": "tts.home_assistant_cloud",
        "tv": DEVICE,
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
    "kids_bedtime_lock.yaml": {
        "tv": DEVICE,
        "kids_profile": "Kids",
    },
    "screen_time_up_notify.yaml": {
        "tv": DEVICE,
        "notify_action": "notify.mobile_app_phone",
    },
    "lights_off_when_idle.yaml": {
        "tv": DEVICE,
        "playing_sensor": "binary_sensor.living_room_tv_playing",
        "lights": ["light.living_room"],
    },
}


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Template triggers (bedtime lock) keep a time listener alive."""
    return True


def test_every_blueprint_has_test_inputs() -> None:
    assert {p.name for p in BLUEPRINT_DIR.glob("*.yaml")} == set(INPUTS)


@pytest.mark.parametrize("filename", sorted(INPUTS))
async def test_blueprint_builds_valid_automation(
    hass: HomeAssistant,
    filename: str,
    request: pytest.FixtureRequest,
    caplog: pytest.LogCaptureFixture,
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

    # Triggers that fail to initialise only log a warning; the entity stays on.
    assert "Error initializing" not in caplog.text

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


async def test_announce_on_tv_sends_tts_voice_clip(
    hass: HomeAssistant, request: pytest.FixtureRequest
) -> None:
    """End to end: the trigger calls play_voice_clip with an encoded TTS media id."""
    target = Path(hass.config.path("blueprints", "automation", DOMAIN))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT_DIR / "announce_on_tv.yaml", target / "announce_on_tv.yaml")
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
    calls = async_mock_service(hass, DOMAIN, "play_voice_clip")

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "id": "under_test",
                "alias": "Under test",
                "use_blueprint": {
                    "path": "android_tv_bridge/announce_on_tv.yaml",
                    "input": {
                        "announce_trigger": [
                            {
                                "trigger": "state",
                                "entity_id": "lock.front_door",
                                "to": "unlocked",
                            }
                        ],
                        "message": "Front door & gate unlocked",
                        "tts_engine": "tts.home_assistant_cloud",
                        "language": "en",
                        "tv": device.id,
                    },
                },
            }
        },
    )
    hass.states.async_set("lock.front_door", "locked")
    await hass.async_block_till_done()
    hass.states.async_set("lock.front_door", "unlocked")
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["media_id"] == (
        "media-source://tts/tts.home_assistant_cloud"
        "?message=Front%20door%20%26%20gate%20unlocked&language=en"
    )
    assert calls[0].data["pause_media"] is True
    assert calls[0].data["device_id"] == [device.id]


async def test_screen_time_up_notify_sends_notification(
    hass: HomeAssistant, request: pytest.FixtureRequest
) -> None:
    """End to end: screen_time_limit_reached calls the chosen notify action."""
    filename = "screen_time_up_notify.yaml"
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
    notify = async_mock_service(hass, "notify", "mobile_app_phone")

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "id": "under_test",
                "use_blueprint": {
                    "path": f"{DOMAIN}/{filename}",
                    "input": {
                        "tv": device.id,
                        "profile": "Kids",
                        "notify_action": "notify.mobile_app_phone",
                    },
                },
            }
        },
    )
    await hass.async_block_till_done()

    def fire(event: str, **data: Any) -> None:
        hass.bus.async_fire(
            f"{DOMAIN}.{event}",
            {"device_id": "launcher-1", "profile_id": 2, "profile": "Kids", **data},
        )

    fire("screen_time_warning", remaining_min=5)  # warnings are off by default
    fire("screen_time_limit_reached", reason="bedtime", profile="Other")
    await hass.async_block_till_done()
    assert notify == []

    fire("screen_time_limit_reached", reason="budget_exhausted")
    await hass.async_block_till_done()
    assert len(notify) == 1
    assert notify[0].data["title"] == "Screen time is up"
    assert notify[0].data["message"].startswith("Kids has used today's screen time")


async def test_kids_bedtime_lock_locks_and_unlocks(
    hass: HomeAssistant, request: pytest.FixtureRequest
) -> None:
    """The lock and unlock times call lock_profile and unlock_profile."""
    from datetime import datetime, timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    filename = "kids_bedtime_lock.yaml"
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
    lock = async_mock_service(hass, DOMAIN, "lock_profile")
    unlock = async_mock_service(hass, DOMAIN, "unlock_profile")
    popup = async_mock_service(hass, DOMAIN, "show_popup")

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "id": "under_test",
                "use_blueprint": {
                    "path": f"{DOMAIN}/{filename}",
                    "input": {
                        "tv": device.id,
                        "kids_profile": "Kids",
                        "lock_time": "20:00:00",
                        "unlock_time": "07:00:00",
                    },
                },
            }
        },
    )
    await hass.async_block_till_done()

    today = dt_util.now().date()
    tz = dt_util.get_default_time_zone()
    async_fire_time_changed(
        hass, datetime(today.year, today.month, today.day, 20, 0, 0, tzinfo=tz)
    )
    await hass.async_block_till_done()
    assert len(lock) == 1
    assert lock[0].data["profile"] == "Kids"
    assert lock[0].data["device_id"] == [device.id]
    assert len(popup) == 1

    tomorrow = today + timedelta(days=1)
    async_fire_time_changed(
        hass, datetime(tomorrow.year, tomorrow.month, tomorrow.day, 7, 0, 0, tzinfo=tz)
    )
    await hass.async_block_till_done()
    assert len(unlock) == 1
