"""Runtime coordinator and WebSocket manager for Android TV Bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import contextlib
from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientWebSocketResponse
from aiohttp import WSMsgType

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STARTED,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .actions import (
    ACTION_EVENT_TYPES,
    BRIDGE_ACTION_RESULT,
    BRIDGE_SET_HA_ACTIONS,
    action_catalog,
    action_result_payload,
    async_run_exposed_action,
    exposed_action_ids,
)
from .client import (
    AndroidTVBridgeAuthError,
    AndroidTVBridgeClient,
    AndroidTVBridgeConnectionError,
    AndroidTVBridgeError,
)
from .const import (
    ATTR_EVENT_TYPE,
    ATTR_HA_DEVICE_ID,
    CONF_API_VERSION,
    CONF_TOKEN,
    CONFIGURATION_PATH,
    DEFAULT_API_VERSION,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EVENT_COMMAND_RESULT,
    EVENT_GENERIC,
    EVENT_MAP,
)
from .issues import async_update_issues
from .media_contract import (
    BRIDGE_MEDIA_COMMAND,
    BRIDGE_VOLUME_COMMAND,
    media_command_payload,
    milliseconds_to_seconds,
    volume_command_payload,
)

_LOGGER = logging.getLogger(__name__)
_UPDATE_INTERVAL = timedelta(seconds=30)


def _first_present(*values: Any) -> Any:
    """Return the first value that is present, preserving falsy values."""
    for value in values:
        if value is not None:
            return value
    return None


def _clean_state(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a launcher state payload into a shallow entity state dict."""
    if not data:
        return {}

    media = data.get("media")
    if not isinstance(media, Mapping):
        media = {}

    network = data.get("network")
    if not isinstance(network, Mapping):
        network = {}

    media_position_ms = _first_present(
        data.get("media_position_ms"),
        media.get("position_ms"),
    )
    media_duration_ms = _first_present(
        data.get("media_duration_ms"),
        media.get("duration_ms"),
    )
    media_position = (
        milliseconds_to_seconds(media_position_ms)
        if media_position_ms is not None
        else _first_present(data.get("media_position"), media.get("position"))
    )
    media_duration = (
        milliseconds_to_seconds(media_duration_ms)
        if media_duration_ms is not None
        else _first_present(data.get("media_duration"), media.get("duration"))
    )
    media_state = _first_present(data.get("media_state"), media.get("state"))

    return {
        **dict(data),
        "foreground_app": data.get("foreground_app") or data.get("foregroundApp"),
        "foreground_package": data.get("foreground_package")
        or data.get("foregroundPackage"),
        "selected_item": data.get("selected_item") or data.get("selectedItem"),
        "launcher_visible": data.get("launcher_visible")
        if "launcher_visible" in data
        else data.get("launcherVisible"),
        "accessibility_enabled": data.get("accessibility_enabled")
        if "accessibility_enabled" in data
        else data.get("accessibilityEnabled"),
        "app_list_version": data.get("app_list_version") or data.get("appListVersion"),
        "last_key": data.get("last_key") or data.get("lastKey"),
        "media_app": _first_present(
            data.get("media_app"),
            media.get("app_name"),
            media.get("app"),
        ),
        "media_title": _first_present(data.get("media_title"), media.get("title")),
        "media_artist": _first_present(data.get("media_artist"), media.get("artist")),
        "media_album": _first_present(data.get("media_album"), media.get("album")),
        "media_state": media_state,
        "media_position": media_position,
        "media_position_ms": media_position_ms,
        "media_duration": media_duration,
        "media_duration_ms": media_duration_ms,
        "media_updated_at": _first_present(
            data.get("media_updated_at"),
            media.get("updated_at"),
            data.get("updated_at"),
        ),
        "media_supported_actions": _first_present(
            data.get("media_supported_actions"),
            media.get("supported_actions"),
        ),
        "media_artwork_url": _first_present(
            data.get("media_artwork_url"),
            media.get("artwork_url"),
        ),
        "playing": data.get("playing")
        if "playing" in data
        else media_state == "playing",
        "idle": data.get("idle"),
        "network_connected": network.get("connected"),
        "network_type": _first_present(data.get("network_type"), network.get("type")),
        "wireless_signal_level": _first_present(
            data.get("wireless_signal_level"),
            network.get("wireless_signal_level"),
            network.get("signal_level"),
        ),
        "has_internet_access": _first_present(
            data.get("has_internet_access"),
            network.get("has_internet_access"),
        ),
        "launcher_mode": data.get("launcher_mode") or data.get("launcherMode"),
        "launcher_modes": data.get("launcher_modes") or data.get("launcherModes"),
        "active_profile": data.get("active_profile") or data.get("activeProfile"),
        "active_profile_id": data.get("active_profile_id")
        or data.get("activeProfileId"),
        "profile_options": data.get("profile_options") or data.get("profileOptions"),
        "profiles": data.get("profiles"),
    }


def _state_from_event(
    event_type: str,
    payload: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the state fields a launcher event carries ahead of its state push.

    The launcher sends ``screen_changed`` before Wi-Fi can drop on standby, so
    the new screen value must land in state even if the state push never comes.
    """
    if event_type == "screen_changed" and payload.get("screen") is not None:
        return {
            "screen": payload["screen"],
            "screen_changed_at": payload.get("timestamp"),
        }
    if event_type == "audio_playing_changed" and "audio_playing" in payload:
        return {"audio_playing": payload["audio_playing"]}
    if event_type == "tv_input_state_changed" and payload.get("id") is not None:
        inputs = current.get("tv_inputs")
        if not isinstance(inputs, list):
            return {}
        updated = [
            {**item, "state": payload.get("state")}
            if isinstance(item, Mapping) and item.get("id") == payload["id"]
            else item
            for item in inputs
        ]
        return {"tv_inputs": updated}
    return {}


class AndroidTVBridgeRuntime:
    """Owns one configured launcher connection."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the runtime."""
        self.hass = hass
        self.entry = entry
        self.metadata: dict[str, Any] = {}
        self.connected = False
        self._stopped = asyncio.Event()
        self._ws_task: asyncio.Task[None] | None = None
        self._websocket: ClientWebSocketResponse | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._unsub_started: CALLBACK_TYPE | None = None

        self.client = AndroidTVBridgeClient(
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            token=entry.data.get(CONF_TOKEN),
            api_version=entry.data.get(CONF_API_VERSION, DEFAULT_API_VERSION),
        )

        self.coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_method=self._async_update_data,
            update_interval=_UPDATE_INTERVAL,
        )

    @property
    def device_id(self) -> str:
        """Return the launcher device identifier."""
        return str(self.metadata.get("device_id") or self.entry.unique_id or self.entry.entry_id)

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return the launcher capabilities (from metadata, newest state wins)."""
        merged: dict[str, Any] = {}
        for source in (self.metadata, self.coordinator.data):
            caps = source.get("capabilities") if isinstance(source, Mapping) else None
            if isinstance(caps, Mapping):
                merged.update(caps)
        return merged

    @property
    def supported_sensors(self) -> set[str]:
        """Return the extra state fields the launcher advertises.

        Comes from ``capabilities.sensors``; old launchers send nothing, so
        entities for those fields are not created.
        """
        sensors = self.capabilities.get("sensors")
        if not isinstance(sensors, list):
            return set()
        return {str(sensor) for sensor in sensors}

    @property
    def screen_off_while_disconnected(self) -> bool:
        """Return True when the WebSocket is down and the screen was last off.

        A TV in standby may drop the bridge connection right after turning the
        screen off. The screen and idle entities keep their state then instead
        of going unavailable (decision D4 in the extra TV sensors plan).
        """
        if self.connected:
            return False
        return (self.coordinator.data or {}).get("screen") == "off"

    @property
    def device_name(self) -> str:
        """Return the launcher display name."""
        return str(
            self.metadata.get("display_name")
            or self.metadata.get("name")
            or self.entry.data.get(CONF_NAME)
            or "SceneTV"
        )

    @property
    def device_info(self) -> dict[str, Any]:
        """Return Home Assistant device info for entities."""
        return {
            "identifiers": {(DOMAIN, self.device_id)},
            "manufacturer": "SceneTV",
            "name": self.device_name,
            "model": self.metadata.get("model") or "Android TV Launcher",
            "sw_version": self.metadata.get("app_version"),
            "configuration_url": (
                f"http://{self.client.host}:{self.client.port}{CONFIGURATION_PATH}"
            ),
        }

    @property
    def ha_device_id(self) -> str | None:
        """Return the Home Assistant device-registry id for this launcher."""
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, self.device_id)}
        )
        return device.id if device is not None else None

    def _event_data(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return the common event data for a launcher event.

        ``device_id`` is the launcher's own id (kept for existing automations);
        ``ha_device_id`` is the Home Assistant device-registry id.
        """
        return {
            "entry_id": self.entry.entry_id,
            "device_id": self.device_id,
            **payload,
            ATTR_HA_DEVICE_ID: self.ha_device_id,
        }

    async def async_start(self) -> None:
        """Start the runtime."""
        self._stopped.clear()
        self.metadata = await self.client.async_get_metadata()
        initial_state = await self.client.async_get_state()
        self.coordinator.async_set_updated_data(
            {
                **_clean_state(initial_state),
                "connection": False,
            }
        )

        if not self.hass.is_running:
            # Scripts and scenes may not be loaded yet; resend names once HA is up.
            self._unsub_started = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_on_hass_started
            )

        first_connection: asyncio.Future[None] = self.hass.loop.create_future()
        self._ws_task = self.hass.async_create_task(self._async_listen(first_connection))
        try:
            await first_connection
        except AndroidTVBridgeError:
            await self.async_stop()
            raise

    async def async_stop(self) -> None:
        """Stop the runtime and reject pending commands."""
        self._stopped.set()
        if self._unsub_started is not None:
            self._unsub_started()
            self._unsub_started = None
        if self._ws_task:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
        for future in self._pending.values():
            if not future.done():
                future.set_exception(HomeAssistantError("Connection closed"))
        self._pending.clear()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            state = await self.client.async_get_state()
        except AndroidTVBridgeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AndroidTVBridgeError as err:
            if self.coordinator.data is not None:
                _LOGGER.debug("State refresh failed; keeping WebSocket state: %s", err)
                return {
                    **self.coordinator.data,
                    "connection": self.connected,
                }
            raise UpdateFailed(str(err)) from err
        data = {
            **(self.coordinator.data or {}),
            **_clean_state(state),
            "connection": self.connected,
        }
        async_update_issues(self.hass, self.entry, self.device_name, data)
        return data

    async def _async_listen(
        self,
        first_connection: asyncio.Future[None] | None = None,
    ) -> None:
        reconnect_delay = 1
        while not self._stopped.is_set():
            try:
                self._websocket = websocket = await self.client.async_open_websocket()
                self.connected = True
                reconnect_delay = 1
                self._merge_state({"connection": True})
                if first_connection is not None and not first_connection.done():
                    first_connection.set_result(None)
                # The command result arrives through this loop, so send from a task.
                self.hass.async_create_task(
                    self.async_push_action_catalog(), f"{DOMAIN} push action catalog"
                )
                async for message in websocket:
                    if message.type == WSMsgType.TEXT:
                        await self._handle_ws_payload(message.json())
                    elif message.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                        break
                # The launcher closed the socket without raising: report it,
                # otherwise entities stay "connected" while the loop sleeps.
                self.connected = False
                self._merge_state({"connection": False})
            except AndroidTVBridgeAuthError as err:
                self.connected = False
                self._merge_state({"connection": False})
                if first_connection is not None and not first_connection.done():
                    first_connection.set_exception(err)
                    return
                _LOGGER.warning(
                    "%s rejected the stored pairing token; starting re-pairing",
                    self.device_name,
                )
                self.entry.async_start_reauth(self.hass)
                return
            except (AndroidTVBridgeConnectionError, ValueError) as err:
                self.connected = False
                self._merge_state({"connection": False})
                _LOGGER.debug("Launcher WebSocket disconnected: %s", err)
                if first_connection is not None and not first_connection.done():
                    first_connection.set_exception(err)
                    return
            finally:
                self._websocket = None
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

    async def _handle_ws_payload(self, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            _LOGGER.debug("Ignoring non-object WebSocket payload: %r", payload)
            return

        message_type = payload.get("type")
        body = payload.get("payload")
        if not isinstance(body, Mapping):
            body = payload

        if message_type in {"state_snapshot", "state_update"}:
            self._merge_state(_clean_state(body))
            return

        if message_type in {"event", "transient_event"}:
            event_type = str(body.get("type") or payload.get("event_type") or "")
            state_update = _state_from_event(
                event_type, body, self.coordinator.data or {}
            )
            if state_update:
                self._merge_state(state_update)
            self._fire_event(event_type, dict(body))
            if event_type in ACTION_EVENT_TYPES:
                self.hass.async_create_task(
                    self._async_handle_action(dict(body)),
                    f"{DOMAIN} action {body.get('action_id')}",
                )
            return

        if message_type in {"command_result", "command_ack"}:
            result = dict(body)
            command_id = str(result.get("command_id") or payload.get("command_id") or "")
            if command_id and "command_id" not in result:
                result["command_id"] = command_id
            if command_id in self._pending and message_type == "command_result":
                self._pending.pop(command_id).set_result(result)
            self._fire_event("command_result", result)

    async def _async_on_hass_started(self, _event: Event) -> None:
        self._unsub_started = None
        if self.connected:
            await self.async_push_action_catalog()

    async def async_push_action_catalog(self) -> None:
        """Send the exposed scripts and scenes to the launcher's tile picker."""
        catalog = action_catalog(self.hass, exposed_action_ids(self.entry))
        try:
            await self.async_send_command(BRIDGE_SET_HA_ACTIONS, {"actions": catalog})
        except HomeAssistantError as err:
            # Launchers without action tiles answer "unsupported_command".
            _LOGGER.debug("Could not send action tiles to the launcher: %s", err)

    async def _async_handle_action(self, payload: dict[str, Any]) -> None:
        """Run an exposed action for a tile or popup press and report back to tiles."""
        result = await async_run_exposed_action(self.hass, self.entry, payload)
        command = action_result_payload(payload, result)
        if command is None:
            return
        try:
            await self.async_send_command(BRIDGE_ACTION_RESULT, command)
        except HomeAssistantError as err:
            _LOGGER.debug("Could not report the action result to the launcher: %s", err)

    def _merge_state(self, update: Mapping[str, Any]) -> None:
        current = self.coordinator.data or {}
        merged = {**current, **dict(update)}
        self.coordinator.async_set_updated_data(merged)
        async_update_issues(self.hass, self.entry, self.device_name, merged)

    def _fire_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if not event_type:
            _LOGGER.debug("Ignoring launcher event without a type: %r", payload)
            return
        event_name = EVENT_MAP.get(event_type)
        if event_name is None:
            event_name = EVENT_GENERIC
            payload = {**payload, ATTR_EVENT_TYPE: event_type}
        self.hass.bus.async_fire(event_name, self._event_data(payload))

    async def async_send_command(
        self,
        command_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Send a command and wait for its final result."""
        if not self.connected:
            raise HomeAssistantError("Launcher WebSocket is not connected")
        if self._ws_task is None:
            raise HomeAssistantError("Launcher connection is not started")

        command_id = str(uuid4())
        timeout = (timeout_ms or DEFAULT_TIMEOUT * 1000) / 1000
        envelope = {
            "command_id": command_id,
            "type": command_type,
            "issued_at": datetime.now(UTC).isoformat(),
            "payload": dict(payload or {}),
            "timeout_ms": timeout_ms or DEFAULT_TIMEOUT * 1000,
        }
        future: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()
        self._pending[command_id] = future

        websocket = self._websocket
        if websocket is None or websocket.closed:
            self._pending.pop(command_id, None)
            raise HomeAssistantError("Launcher WebSocket is not ready")

        try:
            await websocket.send_json(envelope)
        except (ConnectionError, RuntimeError, ClientError) as err:
            self._pending.pop(command_id, None)
            raise HomeAssistantError(f"Could not send command: {err}") from err
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as err:
            self._pending.pop(command_id, None)
            result = {
                "command_id": command_id,
                "status": "timed_out",
                "error": "Timed out waiting for command result",
            }
            self.hass.bus.async_fire(EVENT_COMMAND_RESULT, self._event_data(result))
            raise HomeAssistantError(result["error"]) from err
        if result.get("status") in {"failed", "rejected", "unsupported", "timed_out"}:
            raise HomeAssistantError(str(result.get("error") or result["status"]))
        return result

    async def async_volume_command(self, command: str) -> dict[str, Any]:
        """Send a volume command (up, down, mute, unmute, toggle_mute)."""
        return await self.async_send_command(
            BRIDGE_VOLUME_COMMAND,
            volume_command_payload(command),
        )

    async def async_media_command(self, command: str) -> dict[str, Any]:
        """Send a media control command to the launcher."""
        return await self.async_send_command(
            BRIDGE_MEDIA_COMMAND,
            media_command_payload(command),
        )
