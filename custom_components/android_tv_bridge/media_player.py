"""Media player entities for Android TV Bridge."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AndroidTVBridgeEntity
from .media_contract import (
    HA_MEDIA_STATE_BY_BRIDGE_STATE,
    MEDIA_COMMAND_NEXT,
    MEDIA_COMMAND_PAUSE,
    MEDIA_COMMAND_PLAY,
    MEDIA_COMMAND_PLAY_PAUSE,
    MEDIA_COMMAND_PREVIOUS,
    MEDIA_COMMAND_STOP,
    VOLUME_COMMAND_DOWN,
    VOLUME_COMMAND_MUTE,
    VOLUME_COMMAND_UNMUTE,
    VOLUME_COMMAND_UP,
    volume_steps,
)
from .runtime import AndroidTVBridgeRuntime

_SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
)
_VOLUME_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge media player entities."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AndroidTVBridgeMediaPlayer(runtime)])


class AndroidTVBridgeMediaPlayer(AndroidTVBridgeEntity, MediaPlayerEntity):
    """Media player backed by the active SceneTV Android media session."""

    def __init__(self, runtime: AndroidTVBridgeRuntime) -> None:
        """Initialize the media player entity."""
        super().__init__(
            runtime,
            MediaPlayerEntityDescription(
                key="media_player",
                translation_key="media_player",
                device_class=MediaPlayerDeviceClass.TV,
            ),
        )

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features; volume needs a launcher that reports volume."""
        if self._volume_value("max") is not None:
            return _SUPPORTED_FEATURES | _VOLUME_FEATURES
        return _SUPPORTED_FEATURES

    @property
    def volume_level(self) -> float | None:
        """Return the volume level between 0 and 1."""
        level = self._volume_value("level")
        maximum = self._volume_value("max")
        try:
            level_f = float(level)
            maximum_f = float(maximum)
        except (TypeError, ValueError):
            return None
        if maximum_f <= 0:
            return None
        return max(0.0, min(1.0, level_f / maximum_f))

    @property
    def is_volume_muted(self) -> bool | None:
        """Return whether the TV is muted."""
        muted = self._volume_value("muted")
        return None if muted is None else bool(muted)

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the Home Assistant media player state."""
        bridge_state = self._state_value("media_state")
        if bridge_state is None:
            return None
        media_state = HA_MEDIA_STATE_BY_BRIDGE_STATE.get(
            str(bridge_state).lower(),
            MediaPlayerState.IDLE,
        )
        return MediaPlayerState(media_state)

    @property
    def app_name(self) -> str | None:
        """Return the current media application."""
        return self._string_state("media_app")

    @property
    def media_title(self) -> str | None:
        """Return the current media title."""
        return self._string_state("media_title")

    @property
    def media_artist(self) -> str | None:
        """Return the current media artist."""
        return self._string_state("media_artist")

    @property
    def media_album_name(self) -> str | None:
        """Return the current media album."""
        return self._string_state("media_album")

    @property
    def media_duration(self) -> int | None:
        """Return media duration in seconds."""
        return self._seconds_state("media_duration")

    @property
    def media_position(self) -> int | None:
        """Return media position in seconds."""
        return self._seconds_state("media_position")

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Return when the media position was last updated."""
        value = self._state_value("media_updated_at")
        if value is None:
            return None
        with contextlib.suppress(ValueError, TypeError):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return None

    @property
    def media_image_url(self) -> str | None:
        """Return current media artwork URL when available."""
        return self._string_state("media_artwork_url")

    async def async_media_play(self) -> None:
        """Send play."""
        await self.runtime.async_media_command(MEDIA_COMMAND_PLAY)

    async def async_media_pause(self) -> None:
        """Send pause."""
        await self.runtime.async_media_command(MEDIA_COMMAND_PAUSE)

    async def async_media_play_pause(self) -> None:
        """Send play/pause toggle."""
        await self.runtime.async_media_command(MEDIA_COMMAND_PLAY_PAUSE)

    async def async_media_stop(self) -> None:
        """Send stop."""
        await self.runtime.async_media_command(MEDIA_COMMAND_STOP)

    async def async_media_next_track(self) -> None:
        """Send next track."""
        await self.runtime.async_media_command(MEDIA_COMMAND_NEXT)

    async def async_media_previous_track(self) -> None:
        """Send previous track."""
        await self.runtime.async_media_command(MEDIA_COMMAND_PREVIOUS)

    async def async_volume_up(self) -> None:
        """Raise the volume by one step."""
        await self.runtime.async_volume_command(VOLUME_COMMAND_UP)

    async def async_volume_down(self) -> None:
        """Lower the volume by one step."""
        await self.runtime.async_volume_command(VOLUME_COMMAND_DOWN)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the TV."""
        await self.runtime.async_volume_command(
            VOLUME_COMMAND_MUTE if mute else VOLUME_COMMAND_UNMUTE
        )

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume by stepping, since the launcher has no absolute set."""
        steps = volume_steps(
            self._volume_value("level"),
            self._volume_value("max"),
            volume,
        )
        command = VOLUME_COMMAND_UP if steps > 0 else VOLUME_COMMAND_DOWN
        for _ in range(abs(steps)):
            await self.runtime.async_volume_command(command)

    def _volume_value(self, key: str) -> Any:
        """Return a volume value from flat or nested launcher state."""
        data = self.coordinator.data or {}
        value = data.get(f"volume_{key}")
        if value is None:
            nested = data.get("volume")
            if isinstance(nested, dict):
                value = nested.get(key)
        return value

    def _state_value(self, key: str) -> Any:
        """Return a coordinator state value."""
        return (self.coordinator.data or {}).get(key)

    def _string_state(self, key: str) -> str | None:
        """Return a coordinator state value as a string."""
        value = self._state_value(key)
        if value is None:
            return None
        return str(value)

    def _seconds_state(self, key: str) -> int | None:
        """Return a coordinator state value as a number."""
        value = self._state_value(key)
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
