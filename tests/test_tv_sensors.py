"""Tests for the extra TV sensors (screen, TV input, audio, category, network)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PORT, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.android_tv_bridge.const import DOMAIN
from custom_components.android_tv_bridge.runtime import AndroidTVBridgeRuntime

LAUNCHER_ID = "launcher-1"
ALL_SENSORS = [
    "screen",
    "tv_input",
    "tv_inputs",
    "audio_playing",
    "audio_output",
    "foreground_app_category",
]
FULL_STATE: dict[str, Any] = {
    "screen": "on",
    "screen_changed_at": "2026-11-13T10:00:00Z",
    "tv_input": "PlayStation 5",
    "tv_input_id": "hdmi2",
    "tv_input_confidence": "opened_by_scenetv",
    "tv_inputs": [
        {"id": "hdmi1", "label": "HDMI 1", "state": "standby"},
        {"id": "hdmi2", "label": "PlayStation 5", "state": "connected"},
    ],
    "audio_playing": True,
    "audio_output": "hdmi_arc",
    "foreground_app_category": "game",
    "network_type": "wifi",
    "wireless_signal_level": 3,
    "has_internet_access": True,
    "idle": False,
}


async def _forever() -> None:
    await asyncio.Event().wait()


async def _setup(
    hass: HomeAssistant,
    state: dict[str, Any],
    sensors: list[str] | None,
    *,
    enable: tuple[tuple[str, str], ...] = (),
) -> tuple[MockConfigEntry, AndroidTVBridgeRuntime]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LAUNCHER_ID,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for platform, key in enable:
        # Pre-registered entities start enabled, even if disabled by default.
        registry.async_get_or_create(
            platform, DOMAIN, f"{LAUNCHER_ID}_{key}", config_entry=entry
        )
    capabilities: dict[str, Any] = {"commands": []}
    if sensors is not None:
        capabilities["sensors"] = sensors

    async def fake_start(self: AndroidTVBridgeRuntime) -> None:
        self.metadata = {
            "device_id": LAUNCHER_ID,
            "display_name": "TV",
            "capabilities": capabilities,
        }
        self.connected = True
        self.coordinator.async_set_updated_data({**state, "connection": True})
        self._ws_task = hass.async_create_background_task(_forever(), "fake ws")

    with patch.object(AndroidTVBridgeRuntime, "async_start", fake_start):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{LAUNCHER_ID}_{key}"
    )


def _state(hass: HomeAssistant, platform: str, key: str):
    entity_id = _entity_id(hass, platform, key)
    assert entity_id is not None, f"{platform}.{key} not created"
    return hass.states.get(entity_id)


async def _disconnect(hass: HomeAssistant, runtime: AndroidTVBridgeRuntime) -> None:
    # What the WebSocket loop does when the socket drops.
    runtime.connected = False
    runtime._merge_state({"connection": False})
    await hass.async_block_till_done()


async def test_old_launcher_gets_only_network_entities(hass: HomeAssistant) -> None:
    await _setup(hass, FULL_STATE, sensors=None)

    for platform, key in (
        ("sensor", "screen"),
        ("sensor", "tv_input"),
        ("sensor", "audio_output"),
        ("sensor", "foreground_app_category"),
        ("binary_sensor", "screen_on"),
        ("binary_sensor", "audio_playing"),
        ("binary_sensor", "gaming"),
        ("binary_sensor", "tv_input_hdmi1"),
    ):
        assert _entity_id(hass, platform, key) is None, key

    assert _state(hass, "sensor", "network_type").state == "wifi"
    assert _state(hass, "binary_sensor", "internet_access").state == STATE_ON
    # Signal level is created but disabled by default.
    entry = er.async_get(hass).async_get(
        _entity_id(hass, "sensor", "wireless_signal_level")
    )
    assert entry is not None and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_entities_follow_capabilities_sensors(hass: HomeAssistant) -> None:
    await _setup(hass, FULL_STATE, sensors=["screen", "audio_playing"])

    assert _state(hass, "sensor", "screen").state == "on"
    assert _state(hass, "binary_sensor", "screen_on").state == STATE_ON
    assert _state(hass, "binary_sensor", "audio_playing").state == STATE_ON
    assert _entity_id(hass, "sensor", "audio_output") is None
    assert _entity_id(hass, "sensor", "tv_input") is None
    assert _entity_id(hass, "binary_sensor", "gaming") is None
    assert _entity_id(hass, "binary_sensor", "tv_input_hdmi2") is None


async def test_capability_added_later_creates_entities(hass: HomeAssistant) -> None:
    _, runtime = await _setup(hass, FULL_STATE, sensors=[])
    assert _entity_id(hass, "sensor", "screen") is None

    runtime._merge_state({"capabilities": {"sensors": ["screen"]}})
    await hass.async_block_till_done()

    assert _state(hass, "sensor", "screen").state == "on"


async def test_values_and_attributes(hass: HomeAssistant) -> None:
    _, runtime = await _setup(
        hass, FULL_STATE, sensors=ALL_SENSORS, enable=(("sensor", "wireless_signal_level"),)
    )

    screen = _state(hass, "sensor", "screen")
    assert screen.state == "on"
    assert screen.attributes["options"] == ["on", "screensaver", "off"]
    assert screen.attributes["changed_at"] == "2026-11-13T10:00:00Z"

    tv_input = _state(hass, "sensor", "tv_input")
    assert tv_input.state == "PlayStation 5"
    assert tv_input.attributes["id"] == "hdmi2"
    assert tv_input.attributes["confidence"] == "opened_by_scenetv"

    assert _state(hass, "sensor", "audio_output").state == "hdmi_arc"
    assert _state(hass, "sensor", "foreground_app_category").state == "game"
    assert _state(hass, "binary_sensor", "gaming").state == STATE_ON
    assert _state(hass, "binary_sensor", "audio_playing").attributes["device_class"] == "sound"
    assert _state(hass, "sensor", "wireless_signal_level").state == "3"

    runtime._merge_state(
        {"screen": "screensaver", "foreground_app_category": "video", "audio_playing": False}
    )
    await hass.async_block_till_done()
    assert _state(hass, "sensor", "screen").state == "screensaver"
    assert _state(hass, "binary_sensor", "screen_on").state == STATE_ON
    assert _state(hass, "binary_sensor", "gaming").state == STATE_OFF
    assert _state(hass, "binary_sensor", "audio_playing").state == STATE_OFF

    runtime._merge_state({"screen": "off", "has_internet_access": False})
    await hass.async_block_till_done()
    assert _state(hass, "sensor", "screen").state == "off"
    assert _state(hass, "binary_sensor", "screen_on").state == STATE_OFF
    assert _state(hass, "binary_sensor", "internet_access").state == STATE_OFF


async def test_nested_network_fields(hass: HomeAssistant) -> None:
    from custom_components.android_tv_bridge.runtime import _clean_state

    cleaned = _clean_state(
        {"network": {"type": "wired", "has_internet_access": False}}
    )
    assert cleaned["network_type"] == "wired"
    assert cleaned["has_internet_access"] is False
    assert _clean_state({"network_type": "wifi"})["network_type"] == "wifi"


async def test_per_input_binary_sensors(hass: HomeAssistant) -> None:
    _, runtime = await _setup(hass, FULL_STATE, sensors=ALL_SENSORS)

    hdmi1 = _state(hass, "binary_sensor", "tv_input_hdmi1")
    hdmi2 = _state(hass, "binary_sensor", "tv_input_hdmi2")
    assert hdmi1.state == STATE_OFF
    assert hdmi1.attributes["state"] == "standby"
    assert hdmi2.state == STATE_ON
    assert hdmi2.attributes["state"] == "connected"
    assert hdmi2.attributes["input_id"] == "hdmi2"
    assert hdmi2.name == "TV PlayStation 5 device"
    entry = er.async_get(hass).async_get(_entity_id(hass, "binary_sensor", "tv_input_hdmi1"))
    assert entry.entity_category is er.EntityCategory.DIAGNOSTIC

    # A new input appears, an existing one changes, one disappears.
    runtime._merge_state(
        {
            "tv_inputs": [
                {"id": "hdmi1", "label": "HDMI 1", "state": "connected"},
                {"id": "hdmi3", "label": "Switch", "state": "disconnected"},
            ]
        }
    )
    await hass.async_block_till_done()
    assert _state(hass, "binary_sensor", "tv_input_hdmi1").state == STATE_ON
    assert _state(hass, "binary_sensor", "tv_input_hdmi3").state == STATE_OFF
    assert _state(hass, "binary_sensor", "tv_input_hdmi2").state == STATE_UNAVAILABLE


async def test_input_sensors_need_tv_inputs_capability(hass: HomeAssistant) -> None:
    await _setup(hass, FULL_STATE, sensors=["tv_input"])
    assert _state(hass, "sensor", "tv_input").state == "PlayStation 5"
    assert _entity_id(hass, "binary_sensor", "tv_input_hdmi1") is None


async def test_events_update_state_before_the_state_push(hass: HomeAssistant) -> None:
    _, runtime = await _setup(hass, FULL_STATE, sensors=ALL_SENSORS)
    events = async_capture_events(hass, f"{DOMAIN}.screen_changed")

    await runtime._handle_ws_payload(
        {
            "type": "event",
            "payload": {
                "type": "screen_changed",
                "screen": "off",
                "previous_screen": "on",
                "timestamp": "2026-11-13T11:00:00Z",
            },
        }
    )
    await runtime._handle_ws_payload(
        {
            "type": "event",
            "payload": {
                "type": "tv_input_state_changed",
                "id": "hdmi1",
                "label": "HDMI 1",
                "state": "connected",
                "previous_state": "standby",
            },
        }
    )
    await runtime._handle_ws_payload(
        {"type": "event", "payload": {"type": "audio_playing_changed", "audio_playing": False}}
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["previous_screen"] == "on"
    screen = _state(hass, "sensor", "screen")
    assert screen.state == "off"
    assert screen.attributes["changed_at"] == "2026-11-13T11:00:00Z"
    assert _state(hass, "binary_sensor", "tv_input_hdmi1").state == STATE_ON
    assert _state(hass, "binary_sensor", "audio_playing").state == STATE_OFF


async def test_disconnect_after_screen_off_keeps_screen_and_idle(
    hass: HomeAssistant,
) -> None:
    _, runtime = await _setup(
        hass, FULL_STATE, sensors=ALL_SENSORS, enable=(("binary_sensor", "idle"),)
    )
    assert _state(hass, "binary_sensor", "idle").state == STATE_OFF

    runtime._merge_state({"screen": "off"})
    await _disconnect(hass, runtime)

    assert _state(hass, "sensor", "screen").state == "off"
    assert _state(hass, "binary_sensor", "screen_on").state == STATE_OFF
    assert _state(hass, "binary_sensor", "idle").state == STATE_ON
    assert _state(hass, "binary_sensor", "connection").state == STATE_OFF
    for platform, key in (
        ("sensor", "tv_input"),
        ("sensor", "foreground_app"),
        ("binary_sensor", "audio_playing"),
        ("binary_sensor", "playing"),
        ("binary_sensor", "tv_input_hdmi2"),
        ("sensor", "network_type"),
    ):
        assert _state(hass, platform, key).state == STATE_UNAVAILABLE, key

    # Reconnecting with the screen back on restores live values.
    runtime.connected = True
    runtime._merge_state({"connection": True, "screen": "on"})
    await hass.async_block_till_done()
    assert _state(hass, "binary_sensor", "screen_on").state == STATE_ON
    assert _state(hass, "binary_sensor", "idle").state == STATE_OFF
    assert _state(hass, "sensor", "tv_input").state == "PlayStation 5"


async def test_disconnect_with_screen_on_makes_everything_unavailable(
    hass: HomeAssistant,
) -> None:
    _, runtime = await _setup(
        hass, FULL_STATE, sensors=ALL_SENSORS, enable=(("binary_sensor", "idle"),)
    )
    await _disconnect(hass, runtime)

    for platform, key in (
        ("sensor", "screen"),
        ("binary_sensor", "screen_on"),
        ("binary_sensor", "idle"),
        ("sensor", "tv_input"),
    ):
        assert _state(hass, platform, key).state == STATE_UNAVAILABLE, key
