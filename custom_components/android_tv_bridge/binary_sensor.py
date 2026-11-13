"""Binary sensor entities for Android TV Bridge."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCREEN_OFF, SCREEN_STATES, TV_INPUT_CONNECTED
from .entity import AndroidTVBridgeEntity
from .runtime import AndroidTVBridgeRuntime


@dataclass(frozen=True, kw_only=True)
class AndroidTVBridgeBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Android TV Bridge binary sensor."""

    value_key: str
    # Launcher field that must be listed in capabilities.sensors, if any.
    required_sensor: str | None = None
    # Stay available when the TV disconnects in standby (decision D4).
    keep_when_screen_off: bool = False
    value_fn: Callable[[Mapping[str, Any]], bool | None] | None = None
    # Value reported while the TV is disconnected with the screen off.
    screen_off_value: bool | None = None


def _screen_on(data: Mapping[str, Any]) -> bool | None:
    screen = data.get("screen")
    if screen not in SCREEN_STATES:
        return None
    return screen != SCREEN_OFF


def _gaming(data: Mapping[str, Any]) -> bool | None:
    category = data.get("foreground_app_category")
    if category is None:
        return None
    return category == "game"


BINARY_SENSORS: tuple[AndroidTVBridgeBinarySensorDescription, ...] = (
    AndroidTVBridgeBinarySensorDescription(
        key="connection",
        translation_key="connection",
        value_key="connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="playing",
        translation_key="playing",
        value_key="playing",
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="launcher_visible",
        translation_key="launcher_visible",
        value_key="launcher_visible",
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="idle",
        translation_key="idle",
        value_key="idle",
        keep_when_screen_off=True,
        screen_off_value=True,
        # Launchers before the activity-tracking release always report false;
        # newer ones compute idle (see capabilities.activity), so opt in.
        entity_registry_enabled_default=False,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="accessibility",
        translation_key="accessibility",
        value_key="accessibility_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="overlay_permission",
        translation_key="overlay_permission",
        value_key="overlay_permission",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="popups_enabled",
        translation_key="popups_enabled",
        value_key="popups_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="screen_on",
        translation_key="screen_on",
        value_key="screen",
        required_sensor="screen",
        keep_when_screen_off=True,
        screen_off_value=False,
        value_fn=_screen_on,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="audio_playing",
        translation_key="audio_playing",
        value_key="audio_playing",
        required_sensor="audio_playing",
        device_class=BinarySensorDeviceClass.SOUND,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="gaming",
        translation_key="gaming",
        value_key="foreground_app_category",
        required_sensor="foreground_app_category",
        value_fn=_gaming,
    ),
    AndroidTVBridgeBinarySensorDescription(
        key="internet_access",
        translation_key="internet_access",
        value_key="has_internet_access",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _tv_inputs(data: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    """Return the passthrough inputs from state, keyed by input id."""
    inputs = (data or {}).get("tv_inputs")
    if not isinstance(inputs, list):
        return {}
    return {
        str(item["id"]): item
        for item in inputs
        if isinstance(item, Mapping) and item.get("id") is not None
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge binary sensors."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()
    added_inputs: set[str] = set()

    @callback
    def _async_add_new() -> None:
        # Entities for optional launcher fields appear once capabilities.sensors
        # lists them; one sensor per passthrough input as inputs show up.
        supported = runtime.supported_sensors
        entities: list[BinarySensorEntity] = []
        for description in BINARY_SENSORS:
            if description.key in added:
                continue
            if (
                description.required_sensor is not None
                and description.required_sensor not in supported
            ):
                continue
            added.add(description.key)
            entities.append(AndroidTVBridgeBinarySensor(runtime, description))
        if "tv_inputs" in supported:
            for input_id, item in _tv_inputs(runtime.coordinator.data).items():
                if input_id in added_inputs:
                    continue
                added_inputs.add(input_id)
                entities.append(
                    AndroidTVBridgeInputBinarySensor(
                        runtime, input_id, str(item.get("label") or input_id)
                    )
                )
        if entities:
            async_add_entities(entities)

    _async_add_new()
    entry.async_on_unload(runtime.coordinator.async_add_listener(_async_add_new))


class AndroidTVBridgeBinarySensor(AndroidTVBridgeEntity, BinarySensorEntity):
    """Binary sensor backed by launcher state."""

    entity_description: AndroidTVBridgeBinarySensorDescription

    @property
    def available(self) -> bool:
        """Keep the connection sensor available so it can report "off"."""
        if self.entity_description.key == "connection":
            return self.coordinator.last_update_success
        return super().available

    @property
    def is_on(self) -> bool | None:
        """Return the current binary state."""
        description = self.entity_description
        if (
            description.keep_when_screen_off
            and description.screen_off_value is not None
            and self.runtime.screen_off_while_disconnected
        ):
            return description.screen_off_value
        data = self.coordinator.data or {}
        if description.value_fn is not None:
            return description.value_fn(data)
        value: Any = data.get(description.value_key)
        if value is None:
            return None
        return bool(value)


class AndroidTVBridgeInputBinarySensor(AndroidTVBridgeEntity, BinarySensorEntity):
    """Whether the device behind one passthrough input is connected and awake."""

    _attr_translation_key = "tv_input_device"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(
        self, runtime: AndroidTVBridgeRuntime, input_id: str, label: str
    ) -> None:
        """Initialize the input sensor."""
        super().__init__(
            runtime,
            BinarySensorEntityDescription(key=f"tv_input_{input_id}"),
        )
        self._input_id = input_id
        self._attr_translation_placeholders = {"input": label}

    @property
    def _input(self) -> Mapping[str, Any] | None:
        return _tv_inputs(self.coordinator.data).get(self._input_id)

    @property
    def available(self) -> bool:
        """Go unavailable when the launcher stops listing this input."""
        return super().available and self._input is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when the input reports a connected device."""
        item = self._input
        if item is None or item.get("state") is None:
            return None
        return item.get("state") == TV_INPUT_CONNECTED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw input state and identifiers."""
        item = self._input or {}
        return {
            "state": item.get("state"),
            "input_id": self._input_id,
            "label": item.get("label"),
        }
