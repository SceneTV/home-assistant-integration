"""Tests for the show_camera service."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.android_tv_bridge.const import DOMAIN

from .test_services import _setup


async def test_show_camera_sends_command_to_every_target(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    for runtime in ctx["runtimes"]:
        runtime.capabilities = {"commands": ["show_camera"]}
    await hass.services.async_call(
        DOMAIN,
        "show_camera",
        {
            "device_id": [device.id for device in ctx["devices"]],
            "camera": "front_door",
            "size": "large",
        },
        blocking=True,
    )
    for runtime in ctx["runtimes"]:
        [(command, payload, timeout)] = runtime.commands
        assert command == "show_camera"
        assert payload == {"camera": "front_door", "size": "large"}
        assert timeout == 12000


async def test_show_camera_needs_launcher_support(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    with pytest.raises(HomeAssistantError, match="does not support camera popups"):
        await hass.services.async_call(
            DOMAIN,
            "show_camera",
            {"entry_id": ctx["entries"][0].entry_id, "camera": "front_door"},
            blocking=True,
        )
    assert ctx["runtimes"][0].commands == []
