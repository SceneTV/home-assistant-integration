"""Time entities for Android TV Bridge (per-profile bedtime window)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .parental import (
    AndroidTVBridgeProfileEntity,
    ProfileEntityDescription,
    async_setup_profile_entities,
    parse_hhmm,
)
from .runtime import AndroidTVBridgeRuntime


@dataclass(frozen=True, kw_only=True)
class AndroidTVBridgeProfileTimeDescription(
    ProfileEntityDescription, TimeEntityDescription
):
    """Describes a per-profile time entity."""


PROFILE_TIMES: tuple[AndroidTVBridgeProfileTimeDescription, ...] = (
    AndroidTVBridgeProfileTimeDescription(
        key="bedtime_start",
        translation_key="profile_bedtime_start",
        value_key="bedtime_start",
    ),
    AndroidTVBridgeProfileTimeDescription(
        key="bedtime_end",
        translation_key="profile_bedtime_end",
        value_key="bedtime_end",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge time entities."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_setup_profile_entities(
        runtime,
        entry,
        async_add_entities,
        PROFILE_TIMES,
        AndroidTVBridgeProfileTime,
    )


class AndroidTVBridgeProfileTime(AndroidTVBridgeProfileEntity, TimeEntity):
    """Bedtime start or end of one profile (local TV time).

    The state is unknown while the profile has no bedtime; use the
    set_profile_policy action with clear_bedtime to remove it.
    """

    entity_description: AndroidTVBridgeProfileTimeDescription

    @property
    def native_value(self) -> time | None:
        """Return the bedtime boundary."""
        return parse_hhmm(self.profile_value)

    async def async_set_value(self, value: time) -> None:
        """Set the bedtime boundary."""
        await self.async_send_profile_command(
            "set_profile_policy",
            {self.entity_description.value_key: value.strftime("%H:%M")},
        )
