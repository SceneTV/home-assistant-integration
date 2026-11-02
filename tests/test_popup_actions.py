"""Tests for actionable popups (buttons that fire android_tv_bridge.popup_action)."""

from __future__ import annotations

import pytest
import voluptuous as vol

from homeassistant.core import HomeAssistant

from custom_components.android_tv_bridge.const import DOMAIN, EVENT_MAP
from custom_components.android_tv_bridge.services import SERVICE_SCHEMAS

from .test_services import _setup

ACTIONS = [
    {"id": "unlock", "label": "Unlock", "style": "destructive"},
    {"id": "script.snooze_doorbell", "label": "Snooze", "data": {"minutes": 10}},
]


def test_popup_action_event_is_mapped() -> None:
    assert EVENT_MAP["popup_action"] == f"{DOMAIN}.popup_action"


async def test_show_popup_sends_actions_and_returns_id(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    response = await hass.services.async_call(
        DOMAIN,
        "show_popup",
        {
            "entry_id": ctx["entries"][0].entry_id,
            "title": "Front door",
            "actions": ACTIONS,
            "dismiss_label": "Ignore",
        },
        blocking=True,
        return_response=True,
    )
    [(command, payload, _)] = ctx["runtimes"][0].commands
    assert command == "show_popup"
    assert payload["actions"] == ACTIONS
    assert payload["dismiss_label"] == "Ignore"
    assert payload["popup_id"]
    assert response == {"popup_id": payload["popup_id"]}


async def test_caller_popup_id_is_shared_across_tvs(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    response = await hass.services.async_call(
        DOMAIN,
        "show_image",
        {
            "entity_id": ["media_player.tv_0", "media_player.tv_1"],
            "image_url": "http://camera.local/snap.jpg",
            "actions": [{"id": "open_gate", "label": "Open gate"}],
            "popup_id": "gate-1",
        },
        blocking=True,
        return_response=True,
    )
    assert response == {"popup_id": "gate-1"}
    for runtime in ctx["runtimes"]:
        [(command, payload, _)] = runtime.commands
        assert command == "show_image"
        assert payload["popup_id"] == "gate-1"


async def test_generated_popup_id_is_shared_across_tvs(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "show_popup",
        {"entity_id": ["media_player.tv_0", "media_player.tv_1"], "text": "hi"},
        blocking=True,
    )
    ids = {runtime.commands[0][1]["popup_id"] for runtime in ctx["runtimes"]}
    assert len(ids) == 1


async def test_plain_popup_still_works_without_response(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    result = await hass.services.async_call(
        DOMAIN,
        "show_popup",
        {"entry_id": ctx["entries"][0].entry_id, "text": "Laundry done"},
        blocking=True,
    )
    assert result is None
    [(_, payload, _)] = ctx["runtimes"][0].commands
    assert "actions" not in payload
    assert payload["text"] == "Laundry done"


async def test_other_services_do_not_offer_a_response(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert hass.services.supports_response(DOMAIN, "show_popup") == "optional"
    assert hass.services.supports_response(DOMAIN, "dismiss_popup") == "none"


@pytest.mark.parametrize(
    "actions",
    [
        [{"label": "no id"}],
        [{"id": "has space"}],
        [{"id": "dismiss"}],
        [{"id": "a"}, {"id": "a"}],
        [{"id": f"a{i}"} for i in range(4)],
        [{"id": "a", "default": True}, {"id": "b", "default": True}],
        [{"id": "a", "label": "x" * 41}],
        [{"id": "a", "style": "blink"}],
        [{"id": "a", "data": "not a dict"}],
    ],
)
def test_invalid_actions_are_rejected(actions: list) -> None:
    with pytest.raises(vol.Invalid):
        SERVICE_SCHEMAS["show_popup"]({"text": "x", "actions": actions})


def test_invalid_popup_id_is_rejected() -> None:
    with pytest.raises(vol.Invalid):
        SERVICE_SCHEMAS["show_popup"]({"text": "x", "popup_id": "bad id"})


def test_action_style_is_case_insensitive() -> None:
    data = SERVICE_SCHEMAS["show_popup"](
        {"text": "x", "actions": [{"id": "go", "style": "Primary"}]}
    )
    assert data["actions"][0]["style"] == "primary"


async def test_popup_action_reaches_the_bus(hass: HomeAssistant) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events

    from .test_events import _runtime

    runtime, _ = _runtime(hass)
    actions = async_capture_events(hass, f"{DOMAIN}.popup_action")
    generic = async_capture_events(hass, f"{DOMAIN}.event")

    await runtime._handle_ws_payload(
        {
            "type": "event",
            "payload": {
                "type": "popup_action",
                "action_id": "unlock",
                "source": "popup",
                "source_id": "door-1",
                "popup_id": "door-1",
                "profile_name": "Tyler",
                "data": {"lock": "lock.front_door"},
            },
        }
    )
    await hass.async_block_till_done()

    assert len(actions) == 1
    assert generic == []
    data = actions[0].data
    assert data["action_id"] == "unlock"
    assert data["popup_id"] == "door-1"
    assert data["data"] == {"lock": "lock.front_door"}
