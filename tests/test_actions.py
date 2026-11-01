"""Tests for Home Assistant action tiles (TV-to-HA actions)."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.android_tv_bridge.actions import (
    action_catalog,
    action_result_payload,
    async_run_exposed_action,
    exposed_action_ids,
)
from custom_components.android_tv_bridge.const import CONF_EXPOSED_ACTIONS, DOMAIN
from custom_components.android_tv_bridge.runtime import AndroidTVBridgeRuntime
from custom_components.android_tv_bridge.services import async_register_services

from .conftest import FakeRuntime

LAUNCHER_ID = "launcher-123"


def _entry(hass: HomeAssistant, exposed: list[str] | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LAUNCHER_ID,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
        options={CONF_EXPOSED_ACTIONS: exposed or []},
    )
    entry.add_to_hass(hass)
    return entry


class RecordingRuntime(AndroidTVBridgeRuntime):
    """Real event handling, but commands are recorded instead of sent."""

    def __init__(self, hass: HomeAssistant, entry: MockConfigEntry) -> None:
        super().__init__(hass, entry)
        self.metadata = {"device_id": LAUNCHER_ID, "display_name": "Living Room TV"}
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def async_send_command(  # type: ignore[override]
        self,
        command_type: str,
        payload: Any = None,
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        self.sent.append((command_type, dict(payload or {})))
        return {"status": "completed"}


def _tile_press(action_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "event",
        "payload": {
            "type": "action_tile_pressed",
            "action_id": action_id,
            "source": "tile",
            "source_id": "5",
            "tile_id": 5,
            "tile_title": "Movie mode",
            "press_id": "p1",
            "profile_id": 1,
            "profile_name": "Living Room",
            **extra,
        },
    }


# ---------------------------------------------------------------- options helpers


async def test_exposed_ids_keep_only_scripts_and_scenes(hass: HomeAssistant) -> None:
    entry = _entry(
        hass,
        ["script.movie_mode", "scene.night", "light.kitchen", "script.movie_mode", " "],
    )
    assert exposed_action_ids(entry) == ["script.movie_mode", "scene.night"]


async def test_catalog_uses_friendly_names_and_icons(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "script.movie_mode", "off", {"friendly_name": "Movie mode", "icon": "mdi:movie"}
    )
    catalog = action_catalog(hass, ["script.movie_mode", "scene.not_loaded_yet"])
    assert catalog == [
        {"id": "script.movie_mode", "name": "Movie mode", "domain": "script", "icon": "mdi:movie"},
        {"id": "scene.not_loaded_yet", "name": "Not loaded yet", "domain": "scene"},
    ]


# ---------------------------------------------------------------- running actions


async def test_exposed_script_runs(hass: HomeAssistant) -> None:
    entry = _entry(hass, ["script.movie_mode"])
    hass.states.async_set("script.movie_mode", "off")
    calls = async_mock_service(hass, "script", "turn_on")
    result = await async_run_exposed_action(hass, entry, {"action_id": "script.movie_mode"})
    assert result == {"status": "completed"}
    assert len(calls) == 1
    assert calls[0].data == {"entity_id": "script.movie_mode"}


async def test_unexposed_action_does_not_run(hass: HomeAssistant) -> None:
    entry = _entry(hass, ["scene.night"])
    hass.states.async_set("script.unlock_door", "off")
    calls = async_mock_service(hass, "script", "turn_on")
    result = await async_run_exposed_action(hass, entry, {"action_id": "script.unlock_door"})
    assert result == {"status": "not_exposed"}
    assert calls == []


async def test_missing_entity_reports_failure(hass: HomeAssistant) -> None:
    entry = _entry(hass, ["scene.night"])
    async_mock_service(hass, "scene", "turn_on")
    result = await async_run_exposed_action(hass, entry, {"action_id": "scene.night"})
    assert result["status"] == "failed"


async def test_service_error_reports_failure(hass: HomeAssistant) -> None:
    from homeassistant.exceptions import HomeAssistantError

    entry = _entry(hass, ["script.broken"])
    hass.states.async_set("script.broken", "off")

    async def _raise(call: ServiceCall) -> None:
        raise HomeAssistantError("Script   exploded")

    hass.services.async_register("script", "turn_on", _raise)
    result = await async_run_exposed_action(hass, entry, {"action_id": "script.broken"})
    assert result == {"status": "failed", "message": "Script exploded"}


def test_result_payload_only_for_tiles() -> None:
    tile = {"action_id": "scene.night", "source": "tile", "source_id": "5", "press_id": "p1"}
    assert action_result_payload(tile, {"status": "completed"}) == {
        "source": "tile",
        "source_id": "5",
        "action_id": "scene.night",
        "status": "completed",
        "press_id": "p1",
    }
    popup = {"action_id": "scene.night", "source": "popup", "source_id": "pop-1"}
    assert action_result_payload(popup, {"status": "completed"}) is None


# ---------------------------------------------------------------- runtime wiring


async def test_tile_press_fires_event_runs_script_and_reports_back(hass: HomeAssistant) -> None:
    entry = _entry(hass, ["script.movie_mode"])
    hass.states.async_set("script.movie_mode", "off")
    calls = async_mock_service(hass, "script", "turn_on")
    events = async_capture_events(hass, f"{DOMAIN}.action_tile_pressed")
    runtime = RecordingRuntime(hass, entry)

    await runtime._handle_ws_payload(_tile_press("script.movie_mode"))
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["action_id"] == "script.movie_mode"
    assert events[0].data["source"] == "tile"
    assert events[0].data["profile_name"] == "Living Room"
    assert len(calls) == 1
    assert runtime.sent == [
        (
            "action_result",
            {
                "source": "tile",
                "source_id": "5",
                "action_id": "script.movie_mode",
                "status": "completed",
                "press_id": "p1",
            },
        )
    ]


async def test_custom_action_id_only_fires_event(hass: HomeAssistant) -> None:
    entry = _entry(hass, [])
    events = async_capture_events(hass, f"{DOMAIN}.action_tile_pressed")
    runtime = RecordingRuntime(hass, entry)

    await runtime._handle_ws_payload(_tile_press("movie_mode"))
    await hass.async_block_till_done()

    assert len(events) == 1
    assert runtime.sent[0][1]["status"] == "not_exposed"


async def test_popup_button_runs_exposed_scene_without_reply(hass: HomeAssistant) -> None:
    entry = _entry(hass, ["scene.night"])
    hass.states.async_set("scene.night", "scening")
    calls = async_mock_service(hass, "scene", "turn_on")
    runtime = RecordingRuntime(hass, entry)

    await runtime._handle_ws_payload(
        {
            "type": "event",
            "payload": {
                "type": "popup_action",
                "action_id": "scene.night",
                "source": "popup",
                "source_id": "pop-1",
                "popup_id": "pop-1",
            },
        }
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert runtime.sent == []


async def test_catalog_push_sends_set_ha_actions(hass: HomeAssistant) -> None:
    entry = _entry(hass, ["scene.night"])
    hass.states.async_set("scene.night", "scening", {"friendly_name": "Night"})
    runtime = RecordingRuntime(hass, entry)
    await runtime.async_push_action_catalog()
    assert runtime.sent == [
        (
            "set_ha_actions",
            {"actions": [{"id": "scene.night", "name": "Night", "domain": "scene"}]},
        )
    ]


# ---------------------------------------------------------------- options flow and service


async def test_options_flow_saves_exposed_actions(hass: HomeAssistant) -> None:
    entry = _entry(hass, [])
    hass.states.async_set("script.movie_mode", "off")
    hass.states.async_set("scene.night", "scening")
    # The flow only builds a form; no need to set the entry up.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_EXPOSED_ACTIONS: ["script.movie_mode", "scene.night"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPOSED_ACTIONS] == ["script.movie_mode", "scene.night"]


async def test_create_action_tile_service(hass: HomeAssistant) -> None:
    entry = _entry(hass, [])
    hass.states.async_set("script.movie_mode", "off", {"friendly_name": "Movie mode"})
    runtime = FakeRuntime("TV")
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    async_register_services(hass)

    await hass.services.async_call(
        DOMAIN,
        "create_action_tile",
        {"action": "script.movie_mode", "subtitle": "Dims the lights"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "create_action_tile",
        {"action_id": "doorbell_snooze", "title": "Snooze doorbell"},
        blocking=True,
    )

    assert runtime.commands == [
        (
            "create_deep_link_shortcut",
            {
                "title": "Movie mode",
                "launch_mode": "ha_action",
                "action_id": "script.movie_mode",
                "subtitle": "Dims the lights",
            },
            None,
        ),
        (
            "create_deep_link_shortcut",
            {
                "title": "Snooze doorbell",
                "launch_mode": "ha_action",
                "action_id": "doorbell_snooze",
            },
            None,
        ),
    ]
