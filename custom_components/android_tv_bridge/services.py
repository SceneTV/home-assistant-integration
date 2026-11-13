"""Services for Android TV Bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import logging
import re
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_extract_referenced_entity_ids

from .const import DOMAIN, EXPOSED_ACTION_DOMAINS
from .media_contract import (
    BRIDGE_MEDIA_COMMAND,
    MEDIA_CONTROL_COMMANDS,
    media_command_payload,
    normalize_media_command,
)
from .runtime import AndroidTVBridgeRuntime

_LOGGER = logging.getLogger(__name__)

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
ACTION_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,64}$"
QUEUE_ITEM_FIELDS = ("uri", "package", "title", "subtitle", "image_url")

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
POPUP_MAX_ACTIONS = 3
POPUP_ACTION_LABEL_MAX = 40
POPUP_ACTION_STYLES = ("default", "primary", "destructive")
POPUP_RESERVED_ACTION_ID = "dismiss"
_POPUP_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")

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
SERVICE_CREATE_ACTION_TILE = "create_action_tile"
SERVICE_SEND_KEY = "send_key"
SERVICE_MEDIA_COMMAND = "media_command"
SERVICE_SHOW_POPUP = "show_popup"
SERVICE_SHOW_IMAGE = "show_image"
SERVICE_SHOW_CAMERA = "show_camera"
SERVICE_PLAY_VOICE_CLIP = "play_voice_clip"
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
SERVICE_SET_PROFILE_POLICY = "set_profile_policy"
SERVICE_GRANT_EXTRA_TIME = "grant_extra_time"
SERVICE_LOCK_PROFILE = "lock_profile"
SERVICE_UNLOCK_PROFILE = "unlock_profile"
SERVICE_SET_PROFILE_RESTRICTED = "set_profile_restricted"
SERVICE_SET_PROFILE_ALLOWED_APPS = "set_profile_allowed_apps"

# Kids profile and screen time services (launcher issue #34).
PROFILE_SERVICES = frozenset(
    {
        SERVICE_SET_PROFILE_POLICY,
        SERVICE_GRANT_EXTRA_TIME,
        SERVICE_LOCK_PROFILE,
        SERVICE_UNLOCK_PROFILE,
        SERVICE_SET_PROFILE_RESTRICTED,
        SERVICE_SET_PROFILE_ALLOWED_APPS,
    }
)
PROFILE_POLICY_KEYS = ("daily_budget_min", "bedtime_start", "bedtime_end")
ALLOWED_APPS_MODES = ("replace", "add", "remove")
MAX_DAILY_BUDGET_MIN = 1440
MAX_EXTRA_TIME_MIN = 720
PROFILE_ERRORS = {
    "unsupported_command": (
        "this SceneTV launcher does not support kids profiles and screen time "
        "yet; update the launcher"
    ),
    "invalid_profile": "no SceneTV profile matches {profile}",
    "profile_locked": "the TV is locked to a profile; unlock it first",
    "launch_blocked": "the profile's policy blocked the launch",
}

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


def _popup_token(value: Any) -> str:
    """Validate a popup_id or action id: 1-64 of letters, digits and _ . : -."""
    text = cv.string(value).strip()
    if not _POPUP_TOKEN.match(text):
        raise vol.Invalid(
            "must be 1 to 64 letters, digits or the characters _ . : -"
        )
    return text


def _popup_action_id(value: Any) -> str:
    text = _popup_token(value)
    if text == POPUP_RESERVED_ACTION_ID:
        raise vol.Invalid('"dismiss" is reserved for the built-in Dismiss button')
    return text


_POPUP_LABEL = vol.All(cv.string, vol.Length(min=1, max=POPUP_ACTION_LABEL_MAX))

_POPUP_ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("id"): _popup_action_id,
        vol.Optional("label"): _POPUP_LABEL,
        vol.Optional("style"): vol.All(vol.Lower, vol.In(POPUP_ACTION_STYLES)),
        vol.Optional("default"): cv.boolean,
        vol.Optional("data"): dict,
    }
)


def _popup_actions(value: Any) -> list[dict[str, Any]]:
    """Validate popup buttons: at most three, unique ids, at most one default."""
    actions = vol.All(cv.ensure_list, [_POPUP_ACTION_SCHEMA])(value)
    if len(actions) > POPUP_MAX_ACTIONS:
        raise vol.Invalid(f"at most {POPUP_MAX_ACTIONS} actions are allowed")
    ids = [action["id"] for action in actions]
    if len(set(ids)) != len(ids):
        raise vol.Invalid("action ids must be unique")
    if sum(1 for action in actions if action.get("default")) > 1:
        raise vol.Invalid("only one action can be the default")
    return actions


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
        vol.Optional("actions"): _popup_actions,
        vol.Optional("popup_id"): _popup_token,
        vol.Optional("dismiss_label"): _POPUP_LABEL,
        # Optional HTML body (HTML, CSS, JavaScript) drawn inside the popup, over any app.
        vol.Optional("html"): cv.string,
        vol.Optional("allow_javascript"): cv.boolean,
        vol.Optional("interactive"): cv.boolean,
        vol.Optional("width_dp"): _web_dimension,
        vol.Optional("height_dp"): _web_dimension,
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


def _hhmm(value: Any) -> str:
    """Validate a local time and return it as "HH:MM" (seconds dropped)."""
    return cv.time(value).strftime("%H:%M")


def _package_list(value: Any) -> list[str]:
    """Validate a list of Android package names (empty entries dropped)."""
    packages = [cv.string(item).strip() for item in cv.ensure_list(value)]
    return [package for package in packages if package]


# Profile is chosen by name (``profile``) or id (``profile_id``), like
# select_profile on the launcher.
_PROFILE_FIELDS = {
    vol.Optional("profile"): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
    vol.Optional("profile_id"): cv.positive_int,
    vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
}


def _profile_schema(fields: Mapping[Any, Any] | None = None) -> vol.All:
    return vol.All(
        _schema({**_PROFILE_FIELDS, **(fields or {})}),
        cv.has_at_least_one_key("profile", "profile_id"),
        cv.has_at_most_one_key("profile", "profile_id"),
    )


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
    SERVICE_CREATE_ACTION_TILE: vol.All(
        _schema(
            {
                vol.Optional("action"): cv.entity_domain(list(EXPOSED_ACTION_DOMAINS)),
                vol.Optional("action_id"): vol.All(cv.string, vol.Match(ACTION_ID_PATTERN)),
                vol.Optional("title"): cv.string,
                vol.Optional("subtitle"): cv.string,
                vol.Optional("image_url"): cv.string,
                vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
            }
        ),
        cv.has_at_least_one_key("action", "action_id"),
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
            vol.Schema({vol.Required("html"): object}, extra=vol.ALLOW_EXTRA),
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
    SERVICE_PLAY_VOICE_CLIP: vol.All(
        _schema(
            {
                vol.Optional("media_id"): vol.All(cv.string, vol.Length(min=1)),
                vol.Optional("url"): vol.All(cv.string, vol.Length(min=1)),
                vol.Optional("title"): cv.string,
                vol.Optional("from"): cv.string,
                vol.Optional("position"): vol.In(POPUP_POSITIONS),
                vol.Optional("autoplay"): cv.boolean,
                vol.Optional("profiles"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("pause_media"): cv.boolean,
                vol.Optional("actions"): _popup_actions,
                vol.Optional("popup_id"): _popup_token,
                vol.Optional("dismiss_label"): _POPUP_LABEL,
                vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int,
            }
        ),
        cv.has_at_most_one_key("media_id", "url"),
        cv.has_at_least_one_key("media_id", "url"),
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
                vol.Optional("allow_javascript"): cv.boolean,
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
    SERVICE_SET_PROFILE_POLICY: vol.All(
        _profile_schema(
            {
                vol.Optional("daily_budget_min"): vol.Any(
                    None,
                    vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=MAX_DAILY_BUDGET_MIN)
                    ),
                ),
                vol.Optional("bedtime_start"): vol.Any(None, _hhmm),
                vol.Optional("bedtime_end"): vol.Any(None, _hhmm),
                vol.Optional("clear_daily_budget"): cv.boolean,
                vol.Optional("clear_bedtime"): cv.boolean,
            }
        ),
        cv.has_at_least_one_key(
            *PROFILE_POLICY_KEYS, "clear_daily_budget", "clear_bedtime"
        ),
    ),
    SERVICE_GRANT_EXTRA_TIME: _profile_schema(
        {
            vol.Required("minutes"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_EXTRA_TIME_MIN)
            ),
        }
    ),
    SERVICE_LOCK_PROFILE: _profile_schema(),
    SERVICE_UNLOCK_PROFILE: _schema({vol.Optional(ATTR_TIMEOUT_MS): cv.positive_int}),
    SERVICE_SET_PROFILE_RESTRICTED: _profile_schema(
        {vol.Required("restricted"): cv.boolean}
    ),
    SERVICE_SET_PROFILE_ALLOWED_APPS: _profile_schema(
        {
            vol.Required("packages"): _package_list,
            vol.Optional("mode", default="replace"): vol.In(ALLOWED_APPS_MODES),
        }
    ),
}


# Services that return {"popup_id": ...} to a script using response_variable.
RESPONSE_SERVICES = frozenset(
    {SERVICE_SHOW_POPUP, SERVICE_SHOW_IMAGE, SERVICE_PLAY_VOICE_CLIP}
)


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
    SERVICE_CREATE_ACTION_TILE: lambda call: (
        "create_deep_link_shortcut",
        _action_tile_payload(call),
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
    # play_voice_clip is built asynchronously (media source resolution) in the
    # service handler; this entry only carries the command name.
    SERVICE_PLAY_VOICE_CLIP: lambda call: ("play_voice_clip", {}),
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
    SERVICE_SET_PROFILE_POLICY: lambda call: (
        "set_profile_policy",
        _profile_policy_payload(call),
    ),
    SERVICE_GRANT_EXTRA_TIME: lambda call: (
        "grant_extra_time",
        {**_profile_target(call), "minutes": call.data["minutes"]},
    ),
    SERVICE_LOCK_PROFILE: lambda call: ("lock_profile", _profile_target(call)),
    SERVICE_UNLOCK_PROFILE: lambda call: ("unlock_profile", {}),
    SERVICE_SET_PROFILE_RESTRICTED: lambda call: (
        "set_profile_restricted",
        {**_profile_target(call), "restricted": call.data["restricted"]},
    ),
    SERVICE_SET_PROFILE_ALLOWED_APPS: lambda call: (
        "set_profile_allowed_apps",
        {
            **_profile_target(call),
            "packages": list(call.data["packages"]),
            "mode": call.data["mode"],
        },
    ),
}


def _profile_target(call: ServiceCall) -> dict[str, Any]:
    """Return the launcher's profile selector: profile_id wins over a name."""
    if "profile_id" in call.data:
        return {"profile_id": call.data["profile_id"]}
    return {"profile": call.data["profile"]}


def _profile_policy_payload(call: ServiceCall) -> dict[str, Any]:
    """Build set_profile_policy: omitted keys stay unchanged, null clears."""
    payload = _profile_target(call)
    for key in PROFILE_POLICY_KEYS:
        if key in call.data:
            payload[key] = call.data[key]
    if call.data.get("clear_daily_budget"):
        payload["daily_budget_min"] = None
    if call.data.get("clear_bedtime"):
        payload["bedtime_start"] = None
        payload["bedtime_end"] = None
    return payload


def _profile_error(err: HomeAssistantError, call: ServiceCall) -> HomeAssistantError:
    """Replace a launcher error code from a profile command with a readable message."""
    text = str(err)
    profile = call.data.get("profile", call.data.get("profile_id"))
    for code, message in PROFILE_ERRORS.items():
        if code in text:
            return HomeAssistantError(
                f"{call.service} failed: {message.format(profile=profile)} ({code})"
            )
    return err


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


def _action_tile_payload(call: ServiceCall) -> dict[str, Any]:
    """Build a create_deep_link_shortcut payload for a Home Assistant action tile.

    ``action`` (a script or scene) wins over a free-form ``action_id``. The tile
    only runs the entity if it is also exposed in the integration options;
    otherwise a press just fires ``android_tv_bridge.action_tile_pressed``.
    """
    action_id: str = call.data.get("action") or call.data["action_id"]
    title = call.data.get("title") or _action_display_name(call, action_id)
    payload: dict[str, Any] = {
        "title": title,
        "launch_mode": "ha_action",
        "action_id": action_id,
    }
    if "subtitle" in call.data:
        payload["subtitle"] = call.data["subtitle"]
    if "image_url" in call.data:
        payload["image_url"] = call.data["image_url"]
    return payload


def _action_display_name(call: ServiceCall, action_id: str) -> str:
    hass = getattr(call, "hass", None)
    state = hass.states.get(action_id) if hass is not None else None
    if state is not None and state.name:
        return state.name
    object_id = action_id.split(".", 1)[-1]
    return object_id.replace("_", " ").strip().capitalize() or action_id


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
        "dismiss_label",
        "html",
        "allow_javascript",
        "interactive",
        "width_dp",
        "height_dp",
    ):
        if field in call.data:
            payload[field] = call.data[field]
    if call.data.get("actions"):
        payload["actions"] = [dict(action) for action in call.data["actions"]]
    # Always send a popup_id, generated here when the caller did not pass one, so
    # every targeted TV uses the same id and the service can return it. Scripts
    # then match android_tv_bridge.popup_action / popup_dismissed on it.
    payload["popup_id"] = call.data.get("popup_id") or uuid4().hex
    return payload


VOICE_CLIP_ERRORS = {
    "invalid_payload": "the launcher rejected the voice clip request",
    "clip_not_found": "the TV could not download the clip (check the URL is reachable from the TV)",
    "clip_too_large": "the clip is larger than the TV accepts",
    "unsupported_audio": "the TV cannot play this audio format",
    "rate_limited": "the TV is receiving voice clips too quickly",
    "popups_disabled": "Home Assistant popups are turned off in the SceneTV settings",
    "voice_clips_disabled": "voice clips are turned off in the SceneTV settings",
    "overlay_permission_required": "SceneTV needs the display-over-other-apps permission",
}


def _voice_clip_source(call: ServiceCall) -> str:
    """Return the media_id or url to resolve, normalising /media paths."""
    media_id = call.data.get("media_id")
    if media_id is None:
        return call.data["url"].strip()
    media_id = media_id.strip()
    if media_id.startswith("/media/"):
        rest = media_id[len("/media/") :]
        if not rest.startswith("local/"):
            rest = f"local/{rest}"
        return f"media-source://media_source/{rest}"
    return media_id


async def _async_voice_clip_url(hass: HomeAssistant, call: ServiceCall) -> str:
    """Resolve the clip to an absolute URL the TV can fetch. No bytes pass through HA."""
    from homeassistant.components import media_source
    from homeassistant.components.media_player.browse_media import (
        async_process_play_media_url,
    )

    source = _voice_clip_source(call)
    try:
        if media_source.is_media_source_id(source):
            source = (await media_source.async_resolve_media(hass, source, None)).url
        # Signs HA paths and makes them absolute using the Home Assistant URL.
        url = async_process_play_media_url(hass, source)
    except HomeAssistantError:
        raise
    except Exception as err:  # media_source raises its own error types
        raise HomeAssistantError(f"Could not resolve the voice clip: {err}") from err
    if not url.startswith(("http://", "https://")):
        raise HomeAssistantError(
            "The voice clip must be an http(s) URL, a media source or a /local/ or /media/ path"
        )
    return url


async def _async_voice_clip_payload(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Build the play_voice_clip payload (url, never audio bytes)."""
    payload: dict[str, Any] = {"url": await _async_voice_clip_url(hass, call)}
    for field in (
        "title",
        "from",
        "position",
        "autoplay",
        "pause_media",
        "dismiss_label",
    ):
        if field in call.data:
            payload[field] = call.data[field]
    if call.data.get("profiles"):
        payload["profiles"] = list(call.data["profiles"])
    if call.data.get("actions"):
        payload["actions"] = [dict(action) for action in call.data["actions"]]
    payload["popup_id"] = call.data.get("popup_id") or uuid4().hex
    return payload


def _require_voice_clip_support(runtime: AndroidTVBridgeRuntime) -> None:
    """Fail clearly when the launcher does not report play_voice_clip."""
    capabilities = getattr(runtime, "capabilities", None) or {}
    commands = capabilities.get("commands")
    if not isinstance(commands, (list, tuple, set)) or "play_voice_clip" not in commands:
        raise HomeAssistantError(
            f"{runtime.device_name} does not support voice clips. "
            "Update the SceneTV launcher to a version with voice clips."
        )


def _voice_clip_error(err: HomeAssistantError) -> HomeAssistantError:
    """Replace a launcher error code with a readable message."""
    text = str(err)
    for code, message in VOICE_CLIP_ERRORS.items():
        if code in text:
            return HomeAssistantError(f"Voice clip not played: {message} ({code})")
    return err


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
        "allow_javascript",
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
    commands = (getattr(runtime, "capabilities", None) or {}).get("commands")
    return isinstance(commands, (list, tuple, set)) and command_type in commands


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

    async def async_handle_service(call: ServiceCall) -> ServiceResponse:
        runtimes = _runtimes_from_call(hass, call)
        if call.service == SERVICE_SHOW_CAMERA:
            results = await asyncio.gather(
                *(_async_show_camera(runtime, call) for runtime in runtimes),
                return_exceptions=True,
            )
            failures = [
                f"{runtime.device_name}: {result}"
                for runtime, result in zip(runtimes, results, strict=True)
                if isinstance(result, Exception)
            ]
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, Exception):
                    raise result
            if len(runtimes) == 1 and isinstance(results[0], Exception):
                raise results[0]
            if failures:
                raise HomeAssistantError(
                    f"{call.service} failed on {len(failures)} of {len(runtimes)} "
                    f"SceneTV launchers: {'; '.join(failures)}"
                )
            return None
        command_type, payload = COMMAND_BUILDERS[call.service](call)
        if call.service == SERVICE_PLAY_VOICE_CLIP:
            for runtime in runtimes:
                _require_voice_clip_support(runtime)
            payload = await _async_voice_clip_payload(hass, call)
        timeout_ms = call.data.get(ATTR_TIMEOUT_MS)
        response: ServiceResponse = None
        if call.return_response and "popup_id" in payload:
            response = {"popup_id": payload["popup_id"]}
        if len(runtimes) == 1:
            try:
                await runtimes[0].async_send_command(
                    command_type, payload, timeout_ms=timeout_ms
                )
            except HomeAssistantError as err:
                if call.service == SERVICE_PLAY_VOICE_CLIP:
                    raise _voice_clip_error(err) from err
                if call.service in PROFILE_SERVICES:
                    raise _profile_error(err, call) from err
                raise
            return response

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
                if call.service == SERVICE_PLAY_VOICE_CLIP and isinstance(
                    result, HomeAssistantError
                ):
                    result = _voice_clip_error(result)
                elif call.service in PROFILE_SERVICES and isinstance(
                    result, HomeAssistantError
                ):
                    result = _profile_error(result, call)
                failures.append(f"{runtime.device_name}: {result}")
            elif isinstance(result, BaseException):
                raise result
        if failures:
            raise HomeAssistantError(
                f"{call.service} failed on {len(failures)} of {len(runtimes)} "
                f"SceneTV launchers: {'; '.join(failures)}"
            )
        return response

    for service, schema in SERVICE_SCHEMAS.items():
        hass.services.async_register(
            DOMAIN,
            service,
            async_handle_service,
            schema=schema,
            supports_response=(
                SupportsResponse.OPTIONAL
                if service in RESPONSE_SERVICES
                else SupportsResponse.NONE
            ),
        )


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
