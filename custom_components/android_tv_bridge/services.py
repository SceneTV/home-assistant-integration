"""Services for Android TV Bridge."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .media_contract import (
    BRIDGE_MEDIA_COMMAND,
    MEDIA_CONTROL_COMMANDS,
    media_command_payload,
    normalize_media_command,
)
from .runtime import AndroidTVBridgeRuntime

_LOGGER = logging.getLogger(__name__)

ATTR_ENTRY_ID = "entry_id"
ATTR_DEVICE_ID = "device_id"
ATTR_TIMEOUT_MS = "timeout_ms"

POPUP_POSITIONS = (
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "center",
)
CAMERA_POPUP_SIZES = ("small", "medium", "large")
CAMERA_DEFAULT_TIMEOUT_MS = 12000
CAMERA_ERROR_MESSAGES = {
    "unknown_camera": "Camera {camera} is not configured on this SceneTV launcher",
    "camera_disabled": "Camera {camera} is disabled on this SceneTV launcher",
    "popups_disabled": "Home Assistant popups are disabled on this SceneTV launcher",
    "overlay_permission_required": "SceneTV is not allowed to draw over other apps",
    "grab_failed": "SceneTV could not get a snapshot from camera {camera}",
    "invalid_payload": "SceneTV rejected the camera popup request",
}
CAMERA_SKIP_REASONS = ("profile_not_targeted",)
POPUP_FONT_SIZES = ("small", "medium", "large", "max")
POPUP_COLORS = (
    "grey",
    "black",
    "indigo",
    "green",
    "red",
    "cyan",
    "teal",
    "amber",
    "pink",
)
POPUP_TRANSPARENCIES = ("0%", "25%", "50%", "75%", "100%")

SUPPORTED_KEY_EVENTS = (
    "DPAD_UP",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",
    "DPAD_CENTER",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "CENTER",
    "SELECT",
    "OK",
    "ENTER",
)

SERVICE_LAUNCH_APP = "launch_app"
SERVICE_LAUNCH_ACTIVITY = "launch_activity"
SERVICE_LAUNCH_INTENT = "launch_intent"
SERVICE_OPEN_URI = "open_uri"
SERVICE_CREATE_DEEP_LINK_SHORTCUT = "create_deep_link_shortcut"
SERVICE_SEND_KEY = "send_key"
SERVICE_MEDIA_COMMAND = "media_command"
SERVICE_SHOW_POPUP = "show_popup"
SERVICE_SHOW_IMAGE = "show_image"
SERVICE_SHOW_CAMERA = "show_camera"
SERVICE_DISMISS_POPUP = "dismiss_popup"
SERVICE_REFRESH_APPS = "refresh_apps"
SERVICE_SET_LAUNCHER_MODE = "set_launcher_mode"
SERVICE_SELECT_PROFILE = "select_profile"

_TARGET_SCHEMA = {
    vol.Optional(ATTR_ENTRY_ID): str,
    vol.Optional(ATTR_DEVICE_ID): str,
}


def _schema(fields: Mapping[Any, Any]) -> vol.Schema:
    return vol.Schema({**_TARGET_SCHEMA, **fields})


def _duration_ms(value: Any) -> int:
    """Validate a popup duration."""
    return vol.All(cv.positive_int, vol.Range(min=1000, max=600000))(value)


def _camera_id(value: Any) -> str:
    """Validate a camera id configured on the TV."""
    camera = cv.string(value).strip()
    if not camera:
        raise vol.Invalid("camera must not be empty")
    return camera


def _profile_list(value: Any) -> list[str]:
    """Validate a list of SceneTV profile ids or names."""
    profiles = [cv.string(item).strip() for item in cv.ensure_list(value)]
    return [profile for profile in profiles if profile]


def _popup_fields(*, include_image: bool) -> dict[Any, Any]:
    """Return shared popup service schema fields."""
    fields: dict[Any, Any] = {
        vol.Optional("title"): cv.string,
        vol.Optional("text"): cv.string,
        vol.Optional("position"): vol.In(POPUP_POSITIONS),
        vol.Optional("font_size"): vol.In(POPUP_FONT_SIZES),
        vol.Optional("color"): vol.In(POPUP_COLORS),
        vol.Optional("transparency"): vol.In(POPUP_TRANSPARENCIES),
        vol.Optional("interrupt"): cv.boolean,
        vol.Optional("icon_url"): cv.url,
        vol.Optional("icon_base64"): cv.string,
        vol.Optional("duration_ms"): _duration_ms,
        vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
    }
    if include_image:
        fields[vol.Optional("image_url")] = cv.url
        fields[vol.Optional("image_base64")] = cv.string
    return fields


def _launch_activity_schema() -> vol.Schema:
    return vol.Any(
        _schema(
            {
                vol.Required("component"): cv.string,
                vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
            }
        ),
        _schema(
            {
                vol.Required("package"): cv.string,
                vol.Required("activity"): cv.string,
                vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
            }
        ),
    )


def _key_event(value: Any) -> str:
    key = cv.string(value).strip().upper()
    if key not in SUPPORTED_KEY_EVENTS:
        raise vol.Invalid("unsupported key event")
    return key


def _media_command(value: Any) -> str:
    command = normalize_media_command(cv.string(value))
    if command not in MEDIA_CONTROL_COMMANDS:
        raise vol.Invalid("unsupported media command")
    return command


SERVICE_SCHEMAS = {
    SERVICE_LAUNCH_APP: _schema(
        {
            vol.Required("package"): cv.string,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_LAUNCH_ACTIVITY: _launch_activity_schema(),
    SERVICE_LAUNCH_INTENT: _schema(
        {
            vol.Required("intent_uri"): cv.string,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_OPEN_URI: _schema(
        {
            vol.Required("uri"): cv.string,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_CREATE_DEEP_LINK_SHORTCUT: vol.All(
        _schema(
            {
                vol.Required("title"): cv.string,
                vol.Optional("subtitle"): cv.string,
                vol.Optional("intent_uri"): cv.string,
                vol.Optional("uri"): cv.string,
                vol.Optional("package"): cv.string,
                vol.Optional("package_name"): cv.string,
                vol.Optional("image_uri"): cv.string,
                vol.Optional("image_url"): cv.string,
                vol.Optional("launch_mode", default="open"): vol.In(("open", "play_then_exit")),
                vol.Optional("enabled", default=True): cv.boolean,
                vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
            }
        ),
        vol.Any(
            vol.Schema({vol.Required("intent_uri"): object}, extra=vol.ALLOW_EXTRA),
            vol.Schema({vol.Required("uri"): object}, extra=vol.ALLOW_EXTRA),
        ),
    ),
    SERVICE_SEND_KEY: _schema(
        {
            vol.Required("key"): _key_event,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_MEDIA_COMMAND: _schema(
        {
            vol.Required("command"): _media_command,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_SHOW_POPUP: vol.All(
        _schema(_popup_fields(include_image=False)),
        vol.Any(
            vol.Schema({vol.Required("text"): object}, extra=vol.ALLOW_EXTRA),
            vol.Schema({vol.Required("title"): object}, extra=vol.ALLOW_EXTRA),
        ),
    ),
    SERVICE_SHOW_IMAGE: vol.All(
        _schema(_popup_fields(include_image=True)),
        vol.Any(
            vol.Schema({vol.Required("image_url"): object}, extra=vol.ALLOW_EXTRA),
            vol.Schema({vol.Required("image_base64"): object}, extra=vol.ALLOW_EXTRA),
        ),
    ),
    SERVICE_SHOW_CAMERA: _schema(
        {
            vol.Required("camera"): _camera_id,
            vol.Optional("title"): cv.string,
            vol.Optional("position"): vol.In(POPUP_POSITIONS),
            vol.Optional("size"): vol.In(CAMERA_POPUP_SIZES),
            vol.Optional("duration_ms"): _duration_ms,
            vol.Optional("interrupt"): cv.boolean,
            vol.Optional("profiles"): _profile_list,
            vol.Optional("pause_media"): cv.boolean,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_DISMISS_POPUP: _schema({vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int}),
    SERVICE_REFRESH_APPS: _schema({vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int}),
    SERVICE_SET_LAUNCHER_MODE: _schema(
        {
            vol.Required("mode"): cv.string,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_SELECT_PROFILE: _schema(
        {
            vol.Required("profile"): cv.string,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
}


COMMAND_BUILDERS: dict[str, Callable[[ServiceCall], tuple[str, dict[str, Any]]]] = {
    SERVICE_LAUNCH_APP: lambda call: ("launch_app", {"package": call.data["package"]}),
    SERVICE_LAUNCH_ACTIVITY: lambda call: (
        "launch_activity",
        _launch_activity_payload(call),
    ),
    SERVICE_LAUNCH_INTENT: lambda call: (
        "launch_intent",
        {"intent_uri": call.data["intent_uri"]},
    ),
    SERVICE_OPEN_URI: lambda call: ("open_uri", {"uri": call.data["uri"]}),
    SERVICE_CREATE_DEEP_LINK_SHORTCUT: lambda call: (
        "create_deep_link_shortcut",
        _deep_link_shortcut_payload(call),
    ),
    SERVICE_SEND_KEY: lambda call: ("send_key", {"key": call.data["key"]}),
    SERVICE_MEDIA_COMMAND: lambda call: (
        BRIDGE_MEDIA_COMMAND,
        media_command_payload(call.data["command"]),
    ),
    SERVICE_SHOW_POPUP: lambda call: (
        "show_popup",
        _popup_payload(call),
    ),
    SERVICE_SHOW_IMAGE: lambda call: (
        "show_image",
        _popup_payload(call),
    ),
    SERVICE_SHOW_CAMERA: lambda call: (
        "show_camera",
        _camera_payload(call),
    ),
    SERVICE_DISMISS_POPUP: lambda call: ("dismiss_popup", {}),
    SERVICE_REFRESH_APPS: lambda call: ("refresh_apps", {}),
    SERVICE_SET_LAUNCHER_MODE: lambda call: (
        "set_launcher_mode",
        {"mode": call.data["mode"]},
    ),
    SERVICE_SELECT_PROFILE: lambda call: (
        "select_profile",
        {"profile": call.data["profile"]},
    ),
}


def _launch_activity_payload(call: ServiceCall) -> dict[str, Any]:
    """Build a launch_activity payload from component or package/activity fields."""
    component = call.data.get("component")
    package = call.data.get("package")
    activity = call.data.get("activity")
    if component:
        return {"component": component}
    return {"package": package, "activity": activity}


def _deep_link_shortcut_payload(call: ServiceCall) -> dict[str, Any]:
    """Build a create_deep_link_shortcut payload from optional service fields."""
    payload: dict[str, Any] = {"title": call.data["title"]}
    for field in (
        "subtitle",
        "intent_uri",
        "uri",
        "package",
        "package_name",
        "image_uri",
        "image_url",
        "launch_mode",
        "enabled",
    ):
        if field in call.data:
            payload[field] = call.data[field]
    return payload


def _popup_payload(call: ServiceCall) -> dict[str, Any]:
    """Build a popup command payload from optional service fields."""
    payload: dict[str, Any] = {}
    for field in (
        "title",
        "text",
        "position",
        "font_size",
        "color",
        "transparency",
        "interrupt",
        "icon_url",
        "icon_base64",
        "image_url",
        "image_base64",
        "duration_ms",
    ):
        if field in call.data:
            payload[field] = call.data[field]
    return payload


def _camera_payload(call: ServiceCall) -> dict[str, Any]:
    """Build a show_camera command payload from optional service fields."""
    payload: dict[str, Any] = {"camera": call.data["camera"]}
    for field in (
        "title",
        "position",
        "size",
        "duration_ms",
        "interrupt",
        "pause_media",
    ):
        if field in call.data:
            payload[field] = call.data[field]
    if call.data.get("profiles"):
        payload["profiles"] = call.data["profiles"]
    return payload


def _supports_command(runtime: AndroidTVBridgeRuntime, command_type: str) -> bool:
    """Return whether the launcher advertises a bridge command."""
    for source in (runtime.coordinator.data or {}, runtime.metadata):
        capabilities = source.get("capabilities")
        if isinstance(capabilities, Mapping):
            commands = capabilities.get("commands")
            if isinstance(commands, list):
                return command_type in commands
    return False


def _camera_skip_reason(result: Mapping[str, Any]) -> str | None:
    """Return why the launcher skipped a camera popup, if it did."""
    details = result.get("result")
    if not isinstance(details, Mapping):
        details = result
    skipped = details.get("skipped")
    if isinstance(skipped, str) and skipped:
        return skipped
    if skipped is True or result.get("status") == "skipped":
        return str(details.get("reason") or "skipped")
    return None


async def _async_show_camera(runtime: AndroidTVBridgeRuntime, call: ServiceCall) -> None:
    """Send show_camera, mapping launcher error codes to clear messages."""
    if not _supports_command(runtime, "show_camera"):
        raise HomeAssistantError(
            f"{runtime.device_name} does not support camera popups; update SceneTV"
        )
    camera = call.data["camera"]
    command_type, payload = COMMAND_BUILDERS[SERVICE_SHOW_CAMERA](call)
    try:
        result = await runtime.async_send_command(
            command_type,
            payload,
            timeout_ms=call.data.get(ATTR_TIMEOUT_MS, CAMERA_DEFAULT_TIMEOUT_MS),
        )
    except HomeAssistantError as err:
        code = str(err).split(":", 1)[0].strip()
        if code in CAMERA_SKIP_REASONS:
            _LOGGER.debug("Camera popup %s skipped by launcher: %s", camera, code)
            return
        if code in CAMERA_ERROR_MESSAGES:
            raise HomeAssistantError(
                CAMERA_ERROR_MESSAGES[code].format(camera=camera)
            ) from err
        raise
    if reason := _camera_skip_reason(result):
        _LOGGER.debug("Camera popup %s skipped by launcher: %s", camera, reason)


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_LAUNCH_APP):
        return

    async def async_handle_service(call: ServiceCall) -> None:
        runtime = _runtime_from_call(hass, call)
        if call.service == SERVICE_SHOW_CAMERA:
            await _async_show_camera(runtime, call)
            return
        command_type, payload = COMMAND_BUILDERS[call.service](call)
        await runtime.async_send_command(
            command_type,
            payload,
            timeout_ms=call.data.get(ATTR_TIMEOUT_MS),
        )

    for service, schema in SERVICE_SCHEMAS.items():
        hass.services.async_register(DOMAIN, service, async_handle_service, schema=schema)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister integration services."""
    for service in SERVICE_SCHEMAS:
        hass.services.async_remove(DOMAIN, service)


def _runtime_from_call(hass: HomeAssistant, call: ServiceCall) -> AndroidTVBridgeRuntime:
    runtimes: dict[str, AndroidTVBridgeRuntime] = hass.data.get(DOMAIN, {})
    if not runtimes:
        raise HomeAssistantError("No Android TV Bridge launchers are configured")

    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        if entry_id in runtimes:
            return runtimes[entry_id]
        raise HomeAssistantError(f"No Android TV Bridge launcher for entry {entry_id}")

    device_id = call.data.get(ATTR_DEVICE_ID)
    if device_id:
        registry = dr.async_get(hass)
        device = registry.async_get(device_id)
        if device is None:
            raise HomeAssistantError(f"No Home Assistant device {device_id}")
        for config_entry_id in device.config_entries:
            if config_entry_id in runtimes:
                return runtimes[config_entry_id]
        raise HomeAssistantError(f"Device {device_id} is not an Android TV Bridge device")

    if len(runtimes) == 1:
        return next(iter(runtimes.values()))

    raise HomeAssistantError("Specify entry_id or device_id")
