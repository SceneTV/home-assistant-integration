"""Sensor entities for Android TV Bridge."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCREEN_STATES
from .entity import AndroidTVBridgeEntity
from .runtime import AndroidTVBridgeRuntime


@dataclass(frozen=True, kw_only=True)
class AndroidTVBridgeSensorDescription(SensorEntityDescription):
    """Describes an Android TV Bridge sensor."""

    value_key: str
    # Launcher field that must be listed in capabilities.sensors, if any.
    required_sensor: str | None = None
    # Stay available with the last state when the TV disconnects in standby.
    keep_when_screen_off: bool = False
    value_fn: Callable[[Mapping[str, Any]], Any] | None = None
    attributes_fn: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None


def _screen_value(data: Mapping[str, Any]) -> str | None:
    screen = data.get("screen")
    return screen if screen in SCREEN_STATES else None


SENSORS: tuple[AndroidTVBridgeSensorDescription, ...] = (
    AndroidTVBridgeSensorDescription(
        key="foreground_app",
        translation_key="foreground_app",
        value_key="foreground_app",
    ),
    AndroidTVBridgeSensorDescription(
        key="foreground_package",
        translation_key="foreground_package",
        value_key="foreground_package",
    ),
    AndroidTVBridgeSensorDescription(
        key="selected_item",
        translation_key="selected_item",
        value_key="selected_item",
        # The launcher does not publish the focused tile yet.
        entity_registry_enabled_default=False,
    ),
    AndroidTVBridgeSensorDescription(
        key="media_app",
        translation_key="media_app",
        value_key="media_app",
    ),
    AndroidTVBridgeSensorDescription(
        key="media_title",
        translation_key="media_title",
        value_key="media_title",
    ),
    AndroidTVBridgeSensorDescription(
        key="media_artist",
        translation_key="media_artist",
        value_key="media_artist",
    ),
    AndroidTVBridgeSensorDescription(
        key="media_album",
        translation_key="media_album",
        value_key="media_album",
    ),
    AndroidTVBridgeSensorDescription(
        key="media_state",
        translation_key="media_state",
        value_key="media_state",
    ),
    AndroidTVBridgeSensorDescription(
        key="media_position",
        translation_key="media_position",
        value_key="media_position",
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    AndroidTVBridgeSensorDescription(
        key="media_duration",
        translation_key="media_duration",
        value_key="media_duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    AndroidTVBridgeSensorDescription(
        key="last_key",
        translation_key="last_key",
        value_key="last_key",
        # The launcher does not publish key presses into state yet.
        entity_registry_enabled_default=False,
    ),
    AndroidTVBridgeSensorDescription(
        key="app_list_version",
        translation_key="app_list_version",
        value_key="app_list_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AndroidTVBridgeSensorDescription(
        key="screen",
        translation_key="screen",
        value_key="screen",
        required_sensor="screen",
        keep_when_screen_off=True,
        device_class=SensorDeviceClass.ENUM,
        options=SCREEN_STATES,
        value_fn=_screen_value,
        attributes_fn=lambda data: {"changed_at": data.get("screen_changed_at")},
    ),
    AndroidTVBridgeSensorDescription(
        key="tv_input",
        translation_key="tv_input",
        value_key="tv_input",
        required_sensor="tv_input",
        attributes_fn=lambda data: {
            "id": data.get("tv_input_id"),
            "confidence": data.get("tv_input_confidence"),
        },
    ),
    AndroidTVBridgeSensorDescription(
        key="audio_output",
        translation_key="audio_output",
        value_key="audio_output",
        required_sensor="audio_output",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AndroidTVBridgeSensorDescription(
        key="foreground_app_category",
        translation_key="foreground_app_category",
        value_key="foreground_app_category",
        required_sensor="foreground_app_category",
    ),
    AndroidTVBridgeSensorDescription(
        key="network_type",
        translation_key="network_type",
        value_key="network_type",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AndroidTVBridgeSensorDescription(
        key="wireless_signal_level",
        translation_key="wireless_signal_level",
        value_key="wireless_signal_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge sensors."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    @callback
    def _async_add_new() -> None:
        # Sensors for optional launcher fields appear once capabilities.sensors
        # lists them, including after a launcher update without a reload.
        supported = runtime.supported_sensors
        new = [
            description
            for description in SENSORS
            if description.key not in added
            and (
                description.required_sensor is None
                or description.required_sensor in supported
            )
        ]
        if not new:
            return
        added.update(description.key for description in new)
        async_add_entities(
            AndroidTVBridgeSensor(runtime, description) for description in new
        )

    _async_add_new()
    entry.async_on_unload(runtime.coordinator.async_add_listener(_async_add_new))


class AndroidTVBridgeSensor(AndroidTVBridgeEntity, SensorEntity):
    """Sensor backed by launcher state."""

    entity_description: AndroidTVBridgeSensorDescription

    @property
    def native_value(self) -> Any:
        """Return the current state value."""
        data = self.coordinator.data or {}
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(data)
        return data.get(self.entity_description.value_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for sensors that describe them."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data or {})
