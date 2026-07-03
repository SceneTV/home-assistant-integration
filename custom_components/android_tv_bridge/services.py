"""Services for Android TV Bridge."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .runtime import AndroidTVBridgeRuntime

ATTR_ENTRY_ID = "entry_id"
ATTR_DEVICE_ID = "device_id"
ATTR_TIMEOUT_MS = "timeout_ms"

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
SERVICE_LAUNCH_INTENT = "launch_intent"
SERVICE_OPEN_URI = "open_uri"
SERVICE_SEND_KEY = "send_key"
SERVICE_MEDIA_COMMAND = "media_command"
SERVICE_SHOW_POPUP = "show_popup"
SERVICE_SHOW_IMAGE = "show_image"
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


def _key_event(value: Any) -> str:
    key = cv.string(value).strip().upper()
    if key not in SUPPORTED_KEY_EVENTS:
        raise vol.Invalid("unsupported key event")
    return key


SERVICE_SCHEMAS = {
    SERVICE_LAUNCH_APP: _schema(
        {
            vol.Required("package"): cv.string,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
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
    SERVICE_SEND_KEY: _schema(
        {
            vol.Required("key"): _key_event,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_MEDIA_COMMAND: _schema(
        {
            vol.Required("command"): vol.In(
                ["play", "pause", "play_pause", "stop", "next", "previous", "seek"]
            ),
            vol.Optional("seek_position_ms"): cv.positive_int,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_SHOW_POPUP: _schema(
        {
            vol.Required("text"): cv.string,
            vol.Optional("title"): cv.string,
            vol.Optional("duration_ms"): cv.positive_int,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_SHOW_IMAGE: _schema(
        {
            vol.Required("image_url"): cv.url,
            vol.Optional("title"): cv.string,
            vol.Optional("duration_ms"): cv.positive_int,
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
    SERVICE_LAUNCH_INTENT: lambda call: (
        "launch_intent",
        {"intent_uri": call.data["intent_uri"]},
    ),
    SERVICE_OPEN_URI: lambda call: ("open_uri", {"uri": call.data["uri"]}),
    SERVICE_SEND_KEY: lambda call: ("send_key", {"key": call.data["key"]}),
    SERVICE_MEDIA_COMMAND: lambda call: (
        "media_command",
        {
            "command": call.data["command"],
            **(
                {"seek_position_ms": call.data["seek_position_ms"]}
                if "seek_position_ms" in call.data
                else {}
            ),
        },
    ),
    SERVICE_SHOW_POPUP: lambda call: (
        "show_popup",
        {
            "text": call.data["text"],
            **({"title": call.data["title"]} if "title" in call.data else {}),
            **(
                {"duration_ms": call.data["duration_ms"]}
                if "duration_ms" in call.data
                else {}
            ),
        },
    ),
    SERVICE_SHOW_IMAGE: lambda call: (
        "show_image",
        {
            "image_url": call.data["image_url"],
            **({"title": call.data["title"]} if "title" in call.data else {}),
            **(
                {"duration_ms": call.data["duration_ms"]}
                if "duration_ms" in call.data
                else {}
            ),
        },
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


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_LAUNCH_APP):
        return

    async def async_handle_service(call: ServiceCall) -> None:
        runtime = _runtime_from_call(hass, call)
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
