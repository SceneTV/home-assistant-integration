"""Binary sensor entities for Android TV Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AndroidTVBridgeEntity
from .runtime import AndroidTVBridgeRuntime


@dataclass(frozen=True, kw_only=True)
class AndroidTVBridgeBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Android TV Bridge binary sensor."""

    value_key: str


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
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge binary sensors."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AndroidTVBridgeBinarySensor(runtime, description)
        for description in BINARY_SENSORS
    )


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
        value: Any = (self.coordinator.data or {}).get(self.entity_description.value_key)
        if value is None:
            return None
        return bool(value)
