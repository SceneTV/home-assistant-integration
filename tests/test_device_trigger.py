"""Tests for SceneTV device triggers."""

from __future__ import annotations

from typing import Any

import pytest

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.components.device_automation.exceptions import (
    InvalidDeviceAutomationConfig,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_get_device_automations,
)

from custom_components.android_tv_bridge.const import DOMAIN
from custom_components.android_tv_bridge.device_trigger import (
    TRIGGERS,
    async_get_trigger_capabilities,
    async_validate_trigger_config,
)

LAUNCHER_ID = "launcher-123"
OTHER_LAUNCHER_ID = "launcher-999"


@pytest.fixture
def device(hass: HomeAssistant) -> dr.DeviceEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LAUNCHER_ID,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
    )
    entry.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, LAUNCHER_ID)}
    )


@pytest.fixture
def calls(hass: HomeAssistant) -> list[ServiceCall]:
    captured: list[ServiceCall] = []

    @callback
    def _record(call: ServiceCall) -> None:
        captured.append(call)

    hass.services.async_register("test", "automation", _record)
    return captured


async def _automation(
    hass: HomeAssistant, device_id: str, trigger_type: str, **extra: Any
) -> None:
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "triggers": [
                        {
                            "platform": "device",
                            "domain": DOMAIN,
                            "device_id": device_id,
                            "type": trigger_type,
                            **extra,
                        }
                    ],
                    "actions": {
                        "service": "test.automation",
                        "data_template": {
                            "type": "{{ trigger.type }}",
                            "event": "{{ trigger.event.event_type }}",
                        },
                    },
                }
            ]
        },
    )
    await hass.async_block_till_done()


def _fire(
    hass: HomeAssistant,
    event: str,
    data: dict[str, Any],
    *,
    launcher_id: str = LAUNCHER_ID,
) -> None:
    hass.bus.async_fire(
        f"{DOMAIN}.{event}", {"device_id": launcher_id, "type": event, **data}
    )


async def test_lists_every_trigger(hass: HomeAssistant, device: dr.DeviceEntry) -> None:
    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device.id
    )
    types = {t["type"] for t in triggers if t["domain"] == DOMAIN}
    assert types == set(TRIGGERS)


async def test_capabilities_only_for_filterable_triggers(hass: HomeAssistant) -> None:
    caps = await async_get_trigger_capabilities(
        hass, {"type": "app_opened", "domain": DOMAIN, "device_id": "x"}
    )
    assert "package" in caps["extra_fields"].schema
    assert (
        await async_get_trigger_capabilities(
            hass, {"type": "popup_shown", "domain": DOMAIN, "device_id": "x"}
        )
        == {}
    )


async def test_playback_started_fires_for_this_tv_only(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "playback_started")

    _fire(hass, "media_started", {"media": {"package": "com.plex"}})
    _fire(
        hass,
        "media_started",
        {"media": {"package": "com.plex"}},
        launcher_id=OTHER_LAUNCHER_ID,
    )
    _fire(hass, "media_paused", {"media": {"package": "com.plex"}})
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data == {
        "type": "playback_started",
        "event": f"{DOMAIN}.media_started",
    }


async def test_matches_on_ha_device_id(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "popup_shown")
    hass.bus.async_fire(
        f"{DOMAIN}.popup_shown", {"device_id": "renamed", "ha_device_id": device.id}
    )
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_app_opened_package_filter(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "app_opened", package="com.netflix.ninja")

    _fire(hass, "foreground_app_changed", {"foreground": {"package": "com.plexapp"}})
    _fire(
        hass,
        "foreground_app_changed",
        {"foreground": {"package": "com.netflix.ninja"}},
    )
    await hass.async_block_till_done()

    assert len(calls) == 1


async def test_profile_filter_matches_name_or_id(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "profile_changed", profile="kids")

    _fire(hass, "profile_changed", {"id": "p1", "name": "Tyler"})
    _fire(hass, "profile_changed", {"id": "p2", "name": "Kids"})
    _fire(hass, "profile_changed", {"id": "kids", "name": "Little ones"})
    await hass.async_block_till_done()

    assert len(calls) == 2


async def test_generic_event_is_matched_by_event_type(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    """A launcher event without a dedicated HA name still triggers."""
    await _automation(hass, device.id, "tile_pressed", action_id="movie_mode")

    hass.bus.async_fire(
        f"{DOMAIN}.event",
        {
            "device_id": LAUNCHER_ID,
            "event_type": "action_tile_pressed",
            "action_id": "movie_mode",
        },
    )
    hass.bus.async_fire(
        f"{DOMAIN}.event",
        {
            "device_id": LAUNCHER_ID,
            "event_type": "popup_action",
            "action_id": "movie_mode",
        },
    )
    _fire(hass, "action_tile_pressed", {"action_id": "movie_mode"})
    _fire(hass, "action_tile_pressed", {"action_id": "other"})
    await hass.async_block_till_done()

    assert len(calls) == 2


async def test_idle_triggers_split_on_idle_flag(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "became_idle")

    _fire(hass, "idle_changed", {"idle": False})
    _fire(hass, "idle_changed", {"idle": True})
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["type"] == "became_idle"


async def test_unsupported_extra_field_is_rejected(
    hass: HomeAssistant, device: dr.DeviceEntry
) -> None:
    base = {"platform": "device", "domain": DOMAIN, "device_id": device.id}
    with pytest.raises(InvalidDeviceAutomationConfig):
        await async_validate_trigger_config(
            hass, {**base, "type": "popup_shown", "package": "com.plex"}
        )
    config = await async_validate_trigger_config(
        hass, {**base, "type": "app_opened", "package": "com.plex"}
    )
    assert config["package"] == "com.plex"


async def test_voice_clip_played_fires_for_this_tv_only(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "voice_clip_played")

    _fire(hass, "voice_clip_finished", {"clip_id": "c1", "listened_ms": 4200})
    _fire(hass, "voice_clip_finished", {"clip_id": "c2"}, launcher_id=OTHER_LAUNCHER_ID)
    await hass.async_block_till_done()

    assert len(calls) == 1


async def test_screen_time_limit_reached_filters_on_profile(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "screen_time_limit_reached", profile="kids")

    _fire(
        hass,
        "screen_time_limit_reached",
        {"profile_id": 2, "profile": "Kids", "reason": "budget_exhausted"},
    )
    _fire(
        hass,
        "screen_time_limit_reached",
        {"profile_id": 1, "profile": "Living Room", "reason": "bedtime"},
    )
    _fire(
        hass,
        "screen_time_limit_reached",
        {"profile_id": 2, "profile": "Kids", "reason": "bedtime"},
        launcher_id=OTHER_LAUNCHER_ID,
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["event"] == f"{DOMAIN}.screen_time_limit_reached"


async def test_profile_filter_matches_event_profile_id(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "profile_locked", profile="2")

    _fire(hass, "profile_locked", {"profile_id": 2, "profile": "Kids"})
    _fire(hass, "profile_unlocked", {"profile_id": 2, "profile": "Kids"})
    await hass.async_block_till_done()

    assert len(calls) == 1


async def test_parental_enforcement_triggers_split_on_active(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "parental_enforcement_stopped")

    _fire(hass, "parental_enforcement_changed", {"active": True})
    _fire(hass, "parental_enforcement_changed", {"active": False})
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["type"] == "parental_enforcement_stopped"


async def test_launch_blocked_filters_on_package(
    hass: HomeAssistant, device: dr.DeviceEntry, calls: list[ServiceCall]
) -> None:
    await _automation(hass, device.id, "launch_blocked", package="com.netflix.ninja")

    _fire(hass, "launch_blocked", {"package": "com.netflix.ninja", "reason": "not_allowed"})
    _fire(hass, "launch_blocked", {"package": "com.other", "reason": "not_allowed"})
    await hass.async_block_till_done()

    assert len(calls) == 1
