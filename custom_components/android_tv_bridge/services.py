"""Services for Android TV Bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_extract_referenced_entity_ids

from .const import DOMAIN
from .media_contract import (
    BRIDGE_MEDIA_COMMAND,
    MEDIA_CONTROL_COMMANDS,
    media_command_payload,
    normalize_media_command,
)
from .runtime import AndroidTVBridgeRuntime

ATTR_ENTRY_ID = "entry_id"
ATTR_TIMEOUT_MS = "timeout_ms"

TARGET_KEYS = (
    ATTR_DEVICE_ID,
    ATTR_AREA_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
)

WEB_DIMENSION_MIN_DP = 120
WEB_DIMENSION_MAX_DP = 2000
QUEUE_POSITIONS = ("end", "next")
QUEUE_ITEM_FIELDS = ("uri", "package", "title", "subtitle", "image_url")

POPUP_POSITIONS = (
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "center",
)
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
SERVICE_DISMISS_POPUP = "dismiss_popup"
SERVICE_REFRESH_APPS = "refresh_apps"
SERVICE_SET_LAUNCHER_MODE = "set_launcher_mode"
SERVICE_SELECT_PROFILE = "select_profile"
SERVICE_SHOW_WEB_POPUP = "show_web_popup"
SERVICE_QUEUE_ADD = "queue_add"
SERVICE_QUEUE_REMOVE = "queue_remove"
SERVICE_QUEUE_MOVE = "queue_move"
SERVICE_QUEUE_CLEAR = "queue_clear"
SERVICE_QUEUE_PLAY = "queue_play"
SERVICE_QUEUE_NEXT = "queue_next"
SERVICE_QUEUE_PAUSE = "queue_pause"

# entry_id plus the standard HA target fields (device_id, area_id, entity_id,
# floor_id, label_id). A plain string device_id is still accepted.
_TARGET_SCHEMA = {
    vol.Optional(ATTR_ENTRY_ID): str,
    **cv.TARGET_SERVICE_FIELDS,
}


def _schema(fields: Mapping[Any, Any]) -> vol.Schema:
    return vol.Schema({**_TARGET_SCHEMA, **fields})


def _duration_ms(value: Any) -> int:
    """Validate a popup duration."""
    return vol.All(cv.positive_int, vol.Range(min=1000, max=600000))(value)


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


def _web_dimension(value: Any) -> int:
    """Validate a web popup width or height in dp."""
    return vol.All(
        vol.Coerce(int),
        vol.Range(min=WEB_DIMENSION_MIN_DP, max=WEB_DIMENSION_MAX_DP),
    )(value)


QUEUE_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required("uri"): cv.string,
        vol.Optional("package"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("subtitle"): cv.string,
        vol.Optional("image_url"): cv.string,
    }
)


def _queue_item_id(value: Any) -> str:
    item_id = cv.string(value).strip()
    if not item_id:
        raise vol.Invalid("item_id must not be empty")
    return item_id


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
    SERVICE_SHOW_WEB_POPUP: vol.All(
        _schema(
            {
                vol.Exclusive("html", "content"): cv.string,
                vol.Exclusive("url", "content"): cv.url,
                vol.Optional("title"): cv.string,
                vol.Optional("position"): vol.In(POPUP_POSITIONS),
                vol.Optional("duration_ms"): _duration_ms,
                vol.Optional("width_dp"): _web_dimension,
                vol.Optional("height_dp"): _web_dimension,
                vol.Optional("interactive"): cv.boolean,
                vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
            }
        ),
        vol.Any(
            vol.Schema({vol.Required("html"): object}, extra=vol.ALLOW_EXTRA),
            vol.Schema({vol.Required("url"): object}, extra=vol.ALLOW_EXTRA),
            msg="provide exactly one of html or url",
        ),
    ),
    SERVICE_QUEUE_ADD: vol.All(
        _schema(
            {
                vol.Exclusive("items", "queue_items"): vol.All(
                    cv.ensure_list, [QUEUE_ITEM_SCHEMA], vol.Length(min=1)
                ),
                vol.Exclusive("uri", "queue_items"): cv.string,
                vol.Optional("package"): cv.string,
                vol.Optional("title"): cv.string,
                vol.Optional("subtitle"): cv.string,
                vol.Optional("image_url"): cv.string,
                vol.Optional("position"): vol.In(QUEUE_POSITIONS),
                vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
            }
        ),
        vol.Any(
            vol.Schema({vol.Required("items"): object}, extra=vol.ALLOW_EXTRA),
            vol.Schema({vol.Required("uri"): object}, extra=vol.ALLOW_EXTRA),
            msg="provide uri or items",
        ),
    ),
    SERVICE_QUEUE_REMOVE: _schema(
        {
            vol.Required("item_id"): _queue_item_id,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_QUEUE_MOVE: _schema(
        {
            vol.Required("item_id"): _queue_item_id,
            vol.Required("to_index"): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_QUEUE_CLEAR: _schema({vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int}),
    SERVICE_QUEUE_PLAY: _schema(
        {
            vol.Optional("item_id"): _queue_item_id,
            vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
        }
    ),
    SERVICE_QUEUE_NEXT: _schema({vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int}),
    SERVICE_QUEUE_PAUSE: _schema({vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int}),
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
    SERVICE_SHOW_WEB_POPUP: lambda call: (
        "show_web_popup",
        _web_popup_payload(call),
    ),
    SERVICE_QUEUE_ADD: lambda call: ("queue_add", _queue_add_payload(call)),
    SERVICE_QUEUE_REMOVE: lambda call: (
        "queue_remove",
        {"item_id": call.data["item_id"]},
    ),
    SERVICE_QUEUE_MOVE: lambda call: (
        "queue_move",
        {"item_id": call.data["item_id"], "to_index": call.data["to_index"]},
    ),
    SERVICE_QUEUE_CLEAR: lambda call: ("queue_clear", {}),
    SERVICE_QUEUE_PLAY: lambda call: (
        "queue_play",
        {"item_id": call.data["item_id"]} if "item_id" in call.data else {},
    ),
    SERVICE_QUEUE_NEXT: lambda call: ("queue_next", {}),
    SERVICE_QUEUE_PAUSE: lambda call: ("queue_pause", {}),
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


def _web_popup_payload(call: ServiceCall) -> dict[str, Any]:
    """Build a show_web_popup payload (exactly one of html or url)."""
    payload: dict[str, Any] = {}
    for field in (
        "title",
        "html",
        "url",
        "position",
        "duration_ms",
        "width_dp",
        "height_dp",
        "interactive",
    ):
        if field in call.data:
            payload[field] = call.data[field]
    return payload


def _queue_add_payload(call: ServiceCall) -> dict[str, Any]:
    """Build a queue_add payload from an items list or single-item fields."""
    if "items" in call.data:
        items = [dict(item) for item in call.data["items"]]
    else:
        items = [
            {field: call.data[field] for field in QUEUE_ITEM_FIELDS if field in call.data}
        ]
    payload: dict[str, Any] = {"items": items}
    if "position" in call.data:
        payload["position"] = call.data["position"]
    return payload


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_LAUNCH_APP):
        return

    async def async_handle_service(call: ServiceCall) -> None:
        runtimes = _runtimes_from_call(hass, call)
        command_type, payload = COMMAND_BUILDERS[call.service](call)
        timeout_ms = call.data.get(ATTR_TIMEOUT_MS)
        if len(runtimes) == 1:
            await runtimes[0].async_send_command(
                command_type, payload, timeout_ms=timeout_ms
            )
            return

        results = await asyncio.gather(
            *(
                runtime.async_send_command(command_type, payload, timeout_ms=timeout_ms)
                for runtime in runtimes
            ),
            return_exceptions=True,
        )
        failures: list[str] = []
        for runtime, result in zip(runtimes, results, strict=True):
            if isinstance(result, Exception):
                failures.append(f"{runtime.device_name}: {result}")
            elif isinstance(result, BaseException):
                raise result
        if failures:
            raise HomeAssistantError(
                f"{call.service} failed on {len(failures)} of {len(runtimes)} "
                f"SceneTV launchers: {'; '.join(failures)}"
            )

    for service, schema in SERVICE_SCHEMAS.items():
        hass.services.async_register(DOMAIN, service, async_handle_service, schema=schema)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister integration services."""
    for service in SERVICE_SCHEMAS:
        hass.services.async_remove(DOMAIN, service)


def _has_target(call: ServiceCall) -> bool:
    """Return whether the call names any HA target (device, area, entity...)."""
    return any(call.data.get(key) for key in TARGET_KEYS)


def _runtimes_from_call(
    hass: HomeAssistant, call: ServiceCall
) -> list[AndroidTVBridgeRuntime]:
    """Resolve the SceneTV launchers a service call targets.

    Order: ``entry_id``, then the HA target (``device_id``, ``area_id``,
    ``entity_id``, ``floor_id``, ``label_id``), then the single configured
    launcher when there is exactly one.
    """
    runtimes: dict[str, AndroidTVBridgeRuntime] = hass.data.get(DOMAIN, {})
    if not runtimes:
        raise HomeAssistantError("No Android TV Bridge launchers are configured")

    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        if entry_id in runtimes:
            return [runtimes[entry_id]]
        raise HomeAssistantError(f"No Android TV Bridge launcher for entry {entry_id}")

    if _has_target(call):
        matched = _runtimes_for_target(hass, call, runtimes)
        if not matched:
            raise HomeAssistantError(
                "The service target does not include any SceneTV launcher"
            )
        return matched

    if len(runtimes) == 1:
        return [next(iter(runtimes.values()))]

    raise HomeAssistantError(
        "Several SceneTV launchers are configured: choose a device, area or entity target"
    )


def _runtimes_for_target(
    hass: HomeAssistant,
    call: ServiceCall,
    runtimes: Mapping[str, AndroidTVBridgeRuntime],
) -> list[AndroidTVBridgeRuntime]:
    """Map a service target to launcher runtimes via the device registry."""
    selected = async_extract_referenced_entity_ids(hass, call)
    device_ids: set[str] = set(selected.referenced_devices)
    entity_registry = er.async_get(hass)
    for entity_id in selected.referenced | selected.indirectly_referenced:
        entity_entry = entity_registry.async_get(entity_id)
        if entity_entry is not None and entity_entry.device_id:
            device_ids.add(entity_entry.device_id)

    device_registry = dr.async_get(hass)
    matched: dict[str, AndroidTVBridgeRuntime] = {}
    for device_id in device_ids:
        device = device_registry.async_get(device_id)
        if device is None:
            continue
        for config_entry_id in device.config_entries:
            if config_entry_id in runtimes:
                matched[config_entry_id] = runtimes[config_entry_id]
    return list(matched.values())
