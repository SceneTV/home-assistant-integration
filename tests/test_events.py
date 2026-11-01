"""Tests for launcher event pass-through and device info."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.android_tv_bridge.const import DOMAIN
from custom_components.android_tv_bridge.runtime import AndroidTVBridgeRuntime

LAUNCHER_ID = "launcher-123"


def _runtime(hass: HomeAssistant) -> tuple[AndroidTVBridgeRuntime, MockConfigEntry]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LAUNCHER_ID,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
    )
    entry.add_to_hass(hass)
    runtime = AndroidTVBridgeRuntime(hass, entry)
    runtime.metadata = {"device_id": LAUNCHER_ID, "display_name": "Living Room TV"}
    return runtime, entry


async def test_configuration_url_points_at_portal(hass: HomeAssistant) -> None:
    runtime, _ = _runtime(hass)
    assert runtime.device_info["configuration_url"] == "http://192.168.1.50:8765/configure"


async def test_known_event_keeps_name_and_payload(hass: HomeAssistant) -> None:
    runtime, entry = _runtime(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, LAUNCHER_ID)}
    )
    events = async_capture_events(hass, f"{DOMAIN}.media_started")

    await runtime._handle_ws_payload(
        {"type": "event", "payload": {"type": "media_started", "package": "com.plex"}}
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    data = events[0].data
    assert data["entry_id"] == entry.entry_id
    assert data["device_id"] == LAUNCHER_ID  # launcher id, unchanged
    assert data["ha_device_id"] == device.id
    assert data["package"] == "com.plex"
    assert data["type"] == "media_started"


async def test_previously_dropped_events_are_fired(hass: HomeAssistant) -> None:
    runtime, _ = _runtime(hass)
    names = (
        "web_action",
        "home_config_changed",
        "queue_item_started",
        "queue_item_finished",
        "queue_item_failed",
        "queue_paused",
        "queue_finished",
    )
    captured = {name: async_capture_events(hass, f"{DOMAIN}.{name}") for name in names}

    for name in names:
        await runtime._handle_ws_payload(
            {"type": "event", "payload": {"type": name, "item_id": "qi-1"}}
        )
    await hass.async_block_till_done()

    for name in names:
        assert len(captured[name]) == 1, name
        assert captured[name][0].data["item_id"] == "qi-1"


async def test_unknown_event_fires_generic_event(hass: HomeAssistant) -> None:
    runtime, _ = _runtime(hass)
    generic = async_capture_events(hass, f"{DOMAIN}.event")

    await runtime._handle_ws_payload(
        {"type": "event", "payload": {"type": "something_new", "value": 3}}
    )
    await hass.async_block_till_done()

    assert len(generic) == 1
    data = generic[0].data
    assert data["event_type"] == "something_new"
    assert data["value"] == 3
    assert data["device_id"] == LAUNCHER_ID
    assert data["ha_device_id"] is None  # no device registered in this test


async def test_web_action_is_not_also_generic(hass: HomeAssistant) -> None:
    runtime, _ = _runtime(hass)
    generic = async_capture_events(hass, f"{DOMAIN}.event")
    await runtime._handle_ws_payload(
        {"type": "event", "payload": {"type": "web_action", "action": "ok"}}
    )
    await hass.async_block_till_done()
    assert generic == []


async def test_event_without_type_is_ignored(hass: HomeAssistant) -> None:
    runtime, _ = _runtime(hass)
    generic = async_capture_events(hass, f"{DOMAIN}.event")
    await runtime._handle_ws_payload({"type": "event", "payload": {"value": 1}})
    await hass.async_block_till_done()
    assert generic == []
