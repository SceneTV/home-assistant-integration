"""Sensor entities for Android TV Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AndroidTVBridgeEntity
from .runtime import AndroidTVBridgeRuntime


@dataclass(frozen=True, kw_only=True)
class AndroidTVBridgeSensorDescription(SensorEntityDescription):
    """Describes an Android TV Bridge sensor."""

    value_key: str


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
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge sensors."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AndroidTVBridgeSensor(runtime, description) for description in SENSORS
    )


class AndroidTVBridgeSensor(AndroidTVBridgeEntity, SensorEntity):
    """Sensor backed by launcher state."""

    entity_description: AndroidTVBridgeSensorDescription

    @property
    def native_value(self) -> Any:
        """Return the current state value."""
        return (self.coordinator.data or {}).get(self.entity_description.value_key)
