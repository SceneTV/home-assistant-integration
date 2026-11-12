"""Media control contract shared by SceneTV HA platforms."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

BRIDGE_MEDIA_COMMAND = "media_command"

MEDIA_COMMAND_PLAY = "play"
MEDIA_COMMAND_PAUSE = "pause"
MEDIA_COMMAND_PLAY_PAUSE = "play_pause"
MEDIA_COMMAND_STOP = "stop"
MEDIA_COMMAND_NEXT = "next"
MEDIA_COMMAND_PREVIOUS = "previous"
MEDIA_COMMAND_REWIND = "rewind"
MEDIA_COMMAND_FAST_FORWARD = "fast_forward"

MEDIA_CONTROL_COMMANDS: tuple[str, ...] = (
    MEDIA_COMMAND_PLAY,
    MEDIA_COMMAND_PAUSE,
    MEDIA_COMMAND_PLAY_PAUSE,
    MEDIA_COMMAND_STOP,
    MEDIA_COMMAND_NEXT,
    MEDIA_COMMAND_PREVIOUS,
    MEDIA_COMMAND_REWIND,
    MEDIA_COMMAND_FAST_FORWARD,
)

MEDIA_COMMAND_ALIASES = {
    "toggle": MEDIA_COMMAND_PLAY_PAUSE,
    "next_track": MEDIA_COMMAND_NEXT,
    "prev": MEDIA_COMMAND_PREVIOUS,
    "previous_track": MEDIA_COMMAND_PREVIOUS,
}

BRIDGE_VOLUME_COMMAND = "volume_command"

VOLUME_COMMAND_UP = "up"
VOLUME_COMMAND_DOWN = "down"
VOLUME_COMMAND_MUTE = "mute"
VOLUME_COMMAND_UNMUTE = "unmute"
VOLUME_COMMAND_TOGGLE_MUTE = "toggle_mute"

VOLUME_COMMANDS: tuple[str, ...] = (
    VOLUME_COMMAND_UP,
    VOLUME_COMMAND_DOWN,
    VOLUME_COMMAND_MUTE,
    VOLUME_COMMAND_UNMUTE,
    VOLUME_COMMAND_TOGGLE_MUTE,
)

BRIDGE_STATE_PLAYING = "playing"
BRIDGE_STATE_PAUSED = "paused"
BRIDGE_STATE_STOPPED = "stopped"
BRIDGE_STATE_BUFFERING = "buffering"
BRIDGE_STATE_SEEKING = "seeking"
BRIDGE_STATE_UNKNOWN = "unknown"

HA_MEDIA_STATE_BY_BRIDGE_STATE = {
    BRIDGE_STATE_PLAYING: "playing",
    BRIDGE_STATE_PAUSED: "paused",
    BRIDGE_STATE_STOPPED: "idle",
    BRIDGE_STATE_BUFFERING: "buffering",
    BRIDGE_STATE_SEEKING: "buffering",
    BRIDGE_STATE_UNKNOWN: "idle",
}


def normalize_media_command(command: Any) -> str:
    """Normalize a Home Assistant media command into the SceneTV command set."""
    normalized = str(command).strip().lower()
    return MEDIA_COMMAND_ALIASES.get(normalized, normalized)


def media_command_payload(command: Any) -> dict[str, str]:
    """Build the launcher payload for a media command."""
    return {"command": normalize_media_command(command)}


def media_value(data: Mapping[str, Any], key: str) -> Any:
    """Return a flattened media value from top-level or nested launcher state."""
    media = data.get("media")
    if not isinstance(media, Mapping):
        media = {}
    top_level_key = f"media_{key}"
    if top_level_key in data:
        return data[top_level_key]
    return media.get(key)


def milliseconds_to_seconds(value: Any) -> float | None:
    """Convert launcher millisecond values into Home Assistant seconds."""
    if value is None:
        return None
    try:
        return float(value) / 1000
    except (TypeError, ValueError):
        return None


def volume_command_payload(command: Any) -> dict[str, str]:
    """Build the launcher payload for a volume command."""
    return {"command": str(command).strip().lower()}


def volume_steps(level: Any, maximum: Any, target: float) -> int:
    """Return signed volume steps to move from ``level`` towards ``target``.

    ``target`` is a Home Assistant volume level between 0 and 1. The launcher
    only supports relative steps, so ``volume_set`` is emulated with this many
    ``up`` (positive) or ``down`` (negative) commands.
    """
    try:
        current = int(level)
        top = int(maximum)
    except (TypeError, ValueError):
        return 0
    if top <= 0:
        return 0
    wanted = round(max(0.0, min(1.0, float(target))) * top)
    return wanted - max(0, min(current, top))
