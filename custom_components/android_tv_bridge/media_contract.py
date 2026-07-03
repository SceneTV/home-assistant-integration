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
