"""Constants for the Android TV Bridge integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "android_tv_bridge"

CONF_API_VERSION = "api_version"
CONF_TOKEN = "token"

DEFAULT_API_VERSION = "v1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT = 10

ZEROCONF_TYPE = "_scenetv._tcp.local."

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

EVENT_COMMAND_RESULT = f"{DOMAIN}.command_result"
EVENT_GENERIC = f"{DOMAIN}.event"

ATTR_HA_DEVICE_ID = "ha_device_id"
ATTR_EVENT_TYPE = "event_type"

CONFIGURATION_PATH = "/configure"

CONF_EXPOSED_ACTIONS = "exposed_actions"
EXPOSED_ACTION_DOMAINS = ("script", "scene")

EVENT_MAP = {
    "foreground_app_changed": f"{DOMAIN}.foreground_app_changed",
    "media_started": f"{DOMAIN}.media_started",
    "media_paused": f"{DOMAIN}.media_paused",
    "media_stopped": f"{DOMAIN}.media_stopped",
    "media_changed": f"{DOMAIN}.media_changed",
    "remote_key_pressed": f"{DOMAIN}.remote_key_pressed",
    "launcher_focused": f"{DOMAIN}.launcher_focused",
    "launcher_item_selected": f"{DOMAIN}.launcher_item_selected",
    "idle_changed": f"{DOMAIN}.idle_changed",
    "command_result": EVENT_COMMAND_RESULT,
    "popup_shown": f"{DOMAIN}.popup_shown",
    "popup_dismissed": f"{DOMAIN}.popup_dismissed",
    "popup_action": f"{DOMAIN}.popup_action",
    "voice_clip_finished": f"{DOMAIN}.voice_clip_finished",
    "profile_changed": f"{DOMAIN}.profile_changed",
    "web_action": f"{DOMAIN}.web_action",
    "home_config_changed": f"{DOMAIN}.home_config_changed",
    "queue_item_started": f"{DOMAIN}.queue_item_started",
    "queue_item_finished": f"{DOMAIN}.queue_item_finished",
    "queue_item_failed": f"{DOMAIN}.queue_item_failed",
    "queue_paused": f"{DOMAIN}.queue_paused",
    "queue_finished": f"{DOMAIN}.queue_finished",
    "action_tile_pressed": f"{DOMAIN}.action_tile_pressed",
    # Kids profile and screen time (launcher issue #34).
    "launch_blocked": f"{DOMAIN}.launch_blocked",
    "parental_enforcement_changed": f"{DOMAIN}.parental_enforcement_changed",
    "screen_time_warning": f"{DOMAIN}.screen_time_warning",
    "screen_time_limit_reached": f"{DOMAIN}.screen_time_limit_reached",
    "profile_locked": f"{DOMAIN}.profile_locked",
    "profile_unlocked": f"{DOMAIN}.profile_unlocked",
}
"""Launcher event types with a dedicated Home Assistant event name.

Any other launcher event is fired as ``EVENT_GENERIC`` with the launcher's
event type in ``event_type`` so new launcher events reach the bus without an
integration update.
"""
