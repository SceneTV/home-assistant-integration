"""Tests for the play_voice_clip service, its event and its device trigger."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from homeassistant.components.media_source import PlayMedia
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from custom_components.android_tv_bridge.const import DOMAIN, EVENT_MAP
from custom_components.android_tv_bridge.device_trigger import TRIGGERS
from custom_components.android_tv_bridge.services import SERVICE_SCHEMAS

from .test_services import _setup

RESOLVE = "homeassistant.components.media_source.async_resolve_media"


@pytest.fixture(autouse=True)
async def _urls(hass: HomeAssistant) -> None:
    # http provides the secret used to sign media paths for the TV.
    assert await async_setup_component(hass, "http", {})
    hass.config.internal_url = "http://192.168.1.10:8123"
    hass.config.external_url = None


def test_event_and_trigger_are_mapped() -> None:
    assert EVENT_MAP["voice_clip_finished"] == f"{DOMAIN}.voice_clip_finished"
    assert TRIGGERS["voice_clip_played"].launcher_event == "voice_clip_finished"


def test_schema_needs_exactly_one_source() -> None:
    schema = SERVICE_SCHEMAS["play_voice_clip"]
    schema({"url": "http://192.168.1.10/a.mp3"})
    schema({"media_id": "media-source://media_source/local/a.mp3"})
    with pytest.raises(vol.Invalid):
        schema({"title": "none"})
    with pytest.raises(vol.Invalid):
        schema({"url": "http://x/a.mp3", "media_id": "/local/a.mp3"})


def test_schema_reuses_popup_action_rules() -> None:
    schema = SERVICE_SCHEMAS["play_voice_clip"]
    four = [{"id": f"a{i}"} for i in range(4)]
    with pytest.raises(vol.Invalid):
        schema({"url": "http://x/a.mp3", "actions": four})
    with pytest.raises(vol.Invalid):
        schema({"url": "http://x/a.mp3", "actions": [{"id": "dismiss"}]})


async def test_media_source_is_resolved_to_a_url(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    resolved = PlayMedia("http://192.168.1.10:8123/media/local/dinner.mp3", "audio/mpeg")
    with patch(RESOLVE, AsyncMock(return_value=resolved)) as resolve:
        response = await hass.services.async_call(
            DOMAIN,
            "play_voice_clip",
            {
                "entry_id": ctx["entries"][0].entry_id,
                "media_id": "media-source://media_source/local/dinner.mp3",
                "title": "Dinner",
                "from": "Mum",
                "position": "top-left",
                "autoplay": False,
                "profiles": ["Kids"],
                "pause_media": True,
                "actions": [{"id": "coming", "label": "Coming"}],
                "dismiss_label": "Later",
            },
            blocking=True,
            return_response=True,
        )
    resolve.assert_awaited_once()
    [(command, payload, _)] = ctx["runtimes"][0].commands
    assert command == "play_voice_clip"
    assert payload["url"].startswith("http://192.168.1.10:8123/media/local/dinner.mp3")
    assert "media_id" not in payload and "clip_id" not in payload
    assert payload["from"] == "Mum"
    assert payload["autoplay"] is False
    assert payload["profiles"] == ["Kids"]
    assert payload["pause_media"] is True
    assert payload["actions"] == [{"id": "coming", "label": "Coming"}]
    assert payload["popup_id"]
    assert response == {"popup_id": payload["popup_id"]}


async def test_local_path_becomes_absolute_url(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "play_voice_clip",
        {"entry_id": ctx["entries"][0].entry_id, "media_id": "/local/dinner.mp3"},
        blocking=True,
    )
    [(_, payload, _)] = ctx["runtimes"][0].commands
    # Signed so the TV can fetch it without a token.
    assert payload["url"].startswith("http://192.168.1.10:8123/local/dinner.mp3?authSig=")


async def test_media_path_maps_to_local_media_source(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    resolved = PlayMedia("/media/local/a/b.mp3?authSig=1", "audio/mpeg")
    with patch(RESOLVE, AsyncMock(return_value=resolved)) as resolve:
        await hass.services.async_call(
            DOMAIN,
            "play_voice_clip",
            {"entry_id": ctx["entries"][0].entry_id, "media_id": "/media/a/b.mp3"},
            blocking=True,
        )
    assert resolve.await_args.args[1] == "media-source://media_source/local/a/b.mp3"
    [(_, payload, _)] = ctx["runtimes"][0].commands
    assert payload["url"].startswith("http://192.168.1.10:8123/media/local/a/b.mp3")


async def test_plain_url_and_caller_popup_id(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    response = await hass.services.async_call(
        DOMAIN,
        "play_voice_clip",
        {
            "entity_id": ["media_player.tv_0", "media_player.tv_1"],
            "url": "http://192.168.1.20/tts/a.mp3",
            "popup_id": "clip-1",
        },
        blocking=True,
        return_response=True,
    )
    assert response == {"popup_id": "clip-1"}
    for runtime in ctx["runtimes"]:
        [(_, payload, _)] = runtime.commands
        assert payload == {"url": "http://192.168.1.20/tts/a.mp3", "popup_id": "clip-1"}


async def test_unsupported_launcher_fails_clearly(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    ctx["runtimes"][0].capabilities = {"commands": ["show_popup"]}
    with pytest.raises(HomeAssistantError, match="does not support voice clips"):
        await hass.services.async_call(
            DOMAIN,
            "play_voice_clip",
            {"entry_id": ctx["entries"][0].entry_id, "url": "http://x/a.mp3"},
            blocking=True,
        )
    assert ctx["runtimes"][0].commands == []


async def test_unresolvable_media_source_raises(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    with (
        patch(RESOLVE, AsyncMock(side_effect=ValueError("nope"))),
        pytest.raises(HomeAssistantError, match="Could not resolve"),
    ):
        await hass.services.async_call(
            DOMAIN,
            "play_voice_clip",
            {
                "entry_id": ctx["entries"][0].entry_id,
                "media_id": "media-source://tts/x",
            },
            blocking=True,
        )
    assert ctx["runtimes"][0].commands == []


async def test_launcher_error_code_is_explained(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)

    async def _fail(*args, **kwargs):
        raise HomeAssistantError("voice_clips_disabled")

    ctx["runtimes"][0].async_send_command = _fail
    with pytest.raises(HomeAssistantError, match="turned off in the SceneTV settings"):
        await hass.services.async_call(
            DOMAIN,
            "play_voice_clip",
            {"entry_id": ctx["entries"][0].entry_id, "url": "http://x/a.mp3"},
            blocking=True,
        )
