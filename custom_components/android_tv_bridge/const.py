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
    Platform.SELECT,
    Platform.SENSOR,
]

EVENT_COMMAND_RESULT = f"{DOMAIN}.command_result"

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
    "profile_changed": f"{DOMAIN}.profile_changed",
}
