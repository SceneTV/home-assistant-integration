"""Tests for media player volume support."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import MediaPlayerEntityFeature

from custom_components.android_tv_bridge.media_contract import volume_steps
from custom_components.android_tv_bridge.media_player import AndroidTVBridgeMediaPlayer


def test_volume_steps() -> None:
    assert volume_steps(5, 15, 1.0) == 10
    assert volume_steps(5, 15, 0.0) == -5
    assert volume_steps(5, 15, 5 / 15) == 0
    assert volume_steps(None, 15, 0.5) == 0
    assert volume_steps(5, 0, 0.5) == 0
    assert volume_steps(5, 15, 2.0) == 10


class _Coordinator:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.last_update_success = True

    def async_add_listener(self, *args: Any, **kwargs: Any) -> Any:
        return lambda: None


class _Runtime:
    def __init__(self, data: dict[str, Any]) -> None:
        self.coordinator = _Coordinator(data)
        self.device_id = "launcher-1"
        self.device_info = {"identifiers": {("android_tv_bridge", "launcher-1")}}
        self.volume_commands: list[str] = []

    async def async_volume_command(self, command: str) -> dict[str, Any]:
        self.volume_commands.append(command)
        return {}


def _player(data: dict[str, Any]) -> tuple[AndroidTVBridgeMediaPlayer, _Runtime]:
    runtime = _Runtime(data)
    return AndroidTVBridgeMediaPlayer(runtime), runtime  # type: ignore[arg-type]


async def test_volume_features_only_when_reported() -> None:
    player, _ = _player({})
    assert not player.supported_features & MediaPlayerEntityFeature.VOLUME_SET

    player, _ = _player({"volume_level": 3, "volume_max": 15, "volume_muted": False})
    assert player.supported_features & MediaPlayerEntityFeature.VOLUME_SET
    assert player.supported_features & MediaPlayerEntityFeature.VOLUME_STEP
    assert player.supported_features & MediaPlayerEntityFeature.VOLUME_MUTE
    assert player.volume_level == 0.2
    assert player.is_volume_muted is False


async def test_nested_volume_state() -> None:
    player, _ = _player({"volume": {"level": 10, "max": 20, "muted": True}})
    assert player.volume_level == 0.5
    assert player.is_volume_muted is True


async def test_volume_commands() -> None:
    player, runtime = _player({"volume_level": 3, "volume_max": 15, "volume_muted": False})
    await player.async_volume_up()
    await player.async_volume_down()
    await player.async_mute_volume(True)
    await player.async_mute_volume(False)
    assert runtime.volume_commands == ["up", "down", "mute", "unmute"]

    runtime.volume_commands.clear()
    await player.async_set_volume_level(0.4)  # 6 of 15 -> 3 steps up
    assert runtime.volume_commands == ["up", "up", "up"]

    runtime.volume_commands.clear()
    await player.async_set_volume_level(0.0)
    assert runtime.volume_commands == ["down", "down", "down"]


def test_volume_command_payload() -> None:
    from custom_components.android_tv_bridge.media_contract import (
        BRIDGE_VOLUME_COMMAND,
        volume_command_payload,
    )

    assert BRIDGE_VOLUME_COMMAND == "volume_command"
    assert volume_command_payload("toggle_mute") == {"command": "toggle_mute"}
