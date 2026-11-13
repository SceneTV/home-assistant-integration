"""Device triggers for SceneTV Android TV Bridge.

Each trigger listens for a launcher event on the Home Assistant bus and keeps
only the events that came from the selected device. Events are matched by the
launcher id (the ``device_id`` field the integration has always put on its
events), resolved from the HA device through its ``(DOMAIN, launcher_id)``
identifier, so the triggers work whether or not ``ha_device_id`` is present.

A launcher event fires either under its dedicated name
(``android_tv_bridge.<type>``) or, when the integration has no dedicated name
for it yet, as ``android_tv_bridge.event`` with ``event_type`` set. The
triggers listen to both, so a trigger keeps working when a launcher event gets
promoted into ``EVENT_MAP``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.device_automation.exceptions import (
    InvalidDeviceAutomationConfig,
)
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, Event, HassJob, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_EVENT_TYPE,
    DOMAIN,
    EVENT_GENERIC,
    SCREEN_OFF,
    SCREEN_ON,
    SCREEN_SCREENSAVER,
    TV_INPUT_CONNECTED,
)

CONF_PACKAGE = "package"
CONF_PROFILE = "profile"
CONF_ACTION_ID = "action_id"
CONF_INPUT = "input"


def _nested(data: Mapping[str, Any], *path: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _foreground_package(data: Mapping[str, Any]) -> Any:
    return _nested(data, "foreground", "package") or data.get("package")


def _media_package(data: Mapping[str, Any]) -> Any:
    return (
        _nested(data, "media", "package")
        or _nested(data, "media", "session_package")
        or data.get("package")
    )


def _profile_matches(data: Mapping[str, Any], wanted: str) -> bool:
    """Match a profile by name (case-insensitive) or id."""
    candidates = (
        data.get("name"),
        data.get("id"),
        data.get("profile_name"),
        data.get("profile_id"),
        data.get("profile"),
    )
    wanted_folded = wanted.casefold()
    return any(
        candidate is not None and str(candidate).casefold() == wanted_folded
        for candidate in candidates
    )


@dataclass(frozen=True)
class _TriggerSpec:
    """How one trigger type maps onto a launcher event."""

    launcher_event: str
    # Optional extra field the user can fill in, and how to check it.
    extra_field: str | None = None
    extra_matcher: Callable[[Mapping[str, Any], str], bool] | None = None
    # Fixed check on the event payload (for triggers sharing one event).
    payload_check: Callable[[Mapping[str, Any]], bool] | None = None


def _package_matcher(
    getter: Callable[[Mapping[str, Any]], Any],
) -> Callable[[Mapping[str, Any], str], bool]:
    return lambda data, wanted: getter(data) == wanted


def _input_matcher(data: Mapping[str, Any], wanted: str) -> bool:
    """Match a TV input by label (case-insensitive) or id."""
    wanted_folded = wanted.casefold()
    return any(
        candidate is not None and str(candidate).casefold() == wanted_folded
        for candidate in (data.get("label"), data.get("id"))
    )


def _screen_is(value: str) -> Callable[[Mapping[str, Any]], bool]:
    return lambda data: data.get("screen") == value


def _input_woke(data: Mapping[str, Any]) -> bool:
    return data.get("state") == TV_INPUT_CONNECTED and (
        data.get("previous_state") != TV_INPUT_CONNECTED
    )


def _action_matcher(data: Mapping[str, Any], wanted: str) -> bool:
    return data.get("action_id") == wanted or data.get("action") == wanted


TRIGGERS: dict[str, _TriggerSpec] = {
    "app_opened": _TriggerSpec(
        "foreground_app_changed",
        CONF_PACKAGE,
        _package_matcher(_foreground_package),
    ),
    "playback_started": _TriggerSpec(
        "media_started", CONF_PACKAGE, _package_matcher(_media_package)
    ),
    "playback_paused": _TriggerSpec(
        "media_paused", CONF_PACKAGE, _package_matcher(_media_package)
    ),
    "playback_stopped": _TriggerSpec(
        "media_stopped", CONF_PACKAGE, _package_matcher(_media_package)
    ),
    "profile_changed": _TriggerSpec("profile_changed", CONF_PROFILE, _profile_matches),
    "popup_shown": _TriggerSpec("popup_shown"),
    "popup_dismissed": _TriggerSpec("popup_dismissed"),
    "popup_action": _TriggerSpec("popup_action", CONF_ACTION_ID, _action_matcher),
    "voice_clip_played": _TriggerSpec("voice_clip_finished"),
    "tile_pressed": _TriggerSpec(
        "action_tile_pressed", CONF_ACTION_ID, _action_matcher
    ),
    "web_action": _TriggerSpec("web_action", CONF_ACTION_ID, _action_matcher),
    "queue_item_started": _TriggerSpec("queue_item_started"),
    "queue_finished": _TriggerSpec("queue_finished"),
    "became_idle": _TriggerSpec(
        "idle_changed", payload_check=lambda data: data.get("idle") is True
    ),
    "became_active": _TriggerSpec(
        "idle_changed", payload_check=lambda data: data.get("idle") is False
    ),
    # Kids profile and screen time (launcher issue #34).
    "launch_blocked": _TriggerSpec(
        "launch_blocked", CONF_PACKAGE, _package_matcher(lambda d: d.get("package"))
    ),
    "screen_time_warning": _TriggerSpec(
        "screen_time_warning", CONF_PROFILE, _profile_matches
    ),
    "screen_time_limit_reached": _TriggerSpec(
        "screen_time_limit_reached", CONF_PROFILE, _profile_matches
    ),
    "profile_locked": _TriggerSpec("profile_locked", CONF_PROFILE, _profile_matches),
    "profile_unlocked": _TriggerSpec(
        "profile_unlocked", CONF_PROFILE, _profile_matches
    ),
    "parental_enforcement_stopped": _TriggerSpec(
        "parental_enforcement_changed",
        payload_check=lambda data: data.get("active") is False,
    ),
    "parental_enforcement_started": _TriggerSpec(
        "parental_enforcement_changed",
        payload_check=lambda data: data.get("active") is True,
    ),
    "screen_turned_on": _TriggerSpec(
        "screen_changed", payload_check=_screen_is(SCREEN_ON)
    ),
    "screen_turned_off": _TriggerSpec(
        "screen_changed", payload_check=_screen_is(SCREEN_OFF)
    ),
    "screensaver_started": _TriggerSpec(
        "screen_changed", payload_check=_screen_is(SCREEN_SCREENSAVER)
    ),
    "tv_input_device_woke": _TriggerSpec(
        "tv_input_state_changed",
        CONF_INPUT,
        _input_matcher,
        payload_check=_input_woke,
    ),
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(TRIGGERS),
        vol.Optional(CONF_PACKAGE): cv.string,
        vol.Optional(CONF_PROFILE): cv.string,
        vol.Optional(CONF_ACTION_ID): cv.string,
        vol.Optional(CONF_INPUT): cv.string,
    }
)


def _launcher_id(hass: HomeAssistant, device_id: str) -> str | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            return identifier
    return None


async def async_validate_trigger_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType:
    """Validate a trigger config."""
    config = TRIGGER_SCHEMA(config)
    spec = TRIGGERS[config[CONF_TYPE]]
    for field in (CONF_PACKAGE, CONF_PROFILE, CONF_ACTION_ID, CONF_INPUT):
        if field in config and field != spec.extra_field:
            raise InvalidDeviceAutomationConfig(
                f"Trigger type {config[CONF_TYPE]} does not take {field}"
            )
    return config


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """List the triggers a SceneTV device offers."""
    if _launcher_id(hass, device_id) is None:
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in TRIGGERS
    ]


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """Return the optional filter field for a trigger, if it has one."""
    spec = TRIGGERS.get(config[CONF_TYPE])
    if spec is None or spec.extra_field is None:
        return {}
    return {"extra_fields": vol.Schema({vol.Optional(spec.extra_field): str})}


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a device trigger."""
    trigger_type: str = config[CONF_TYPE]
    spec = TRIGGERS[trigger_type]
    ha_device_id: str = config[CONF_DEVICE_ID]
    launcher_id = _launcher_id(hass, ha_device_id)
    wanted = config.get(spec.extra_field) if spec.extra_field else None
    dedicated_event = f"{DOMAIN}.{spec.launcher_event}"
    trigger_data = trigger_info["trigger_data"]
    job = HassJob(action, f"SceneTV device trigger {trigger_info}")

    def _from_device(data: Mapping[str, Any]) -> bool:
        if data.get("ha_device_id") == ha_device_id:
            return True
        return launcher_id is not None and data.get("device_id") == launcher_id

    def _matches(data: Mapping[str, Any]) -> bool:
        if not _from_device(data):
            return False
        if spec.payload_check is not None and not spec.payload_check(data):
            return False
        if wanted and spec.extra_matcher is not None:
            return spec.extra_matcher(data, wanted)
        return True

    @callback
    def _dedicated_filter(event_data: Mapping[str, Any]) -> bool:
        return _matches(event_data)

    @callback
    def _generic_filter(event_data: Mapping[str, Any]) -> bool:
        return event_data.get(ATTR_EVENT_TYPE) == spec.launcher_event and _matches(
            event_data
        )

    @callback
    def _handle(event: Event) -> None:
        hass.async_run_hass_job(
            job,
            {
                "trigger": {
                    **trigger_data,
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: ha_device_id,
                    CONF_TYPE: trigger_type,
                    "event": event,
                    "description": f"SceneTV {trigger_type.replace('_', ' ')}",
                }
            },
            event.context,
        )

    removers = [
        hass.bus.async_listen(dedicated_event, _handle, event_filter=_dedicated_filter),
        hass.bus.async_listen(EVENT_GENERIC, _handle, event_filter=_generic_filter),
    ]

    @callback
    def _remove() -> None:
        for remove in removers:
            remove()

    return _remove
