"""Switch entities for Android TV Bridge (per-profile kids restriction)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .parental import (
    AndroidTVBridgeProfileEntity,
    ProfileEntityDescription,
    async_setup_profile_entities,
)
from .runtime import AndroidTVBridgeRuntime


@dataclass(frozen=True, kw_only=True)
class AndroidTVBridgeProfileSwitchDescription(
    ProfileEntityDescription, SwitchEntityDescription
):
    """Describes a per-profile switch."""


PROFILE_SWITCHES: tuple[AndroidTVBridgeProfileSwitchDescription, ...] = (
    AndroidTVBridgeProfileSwitchDescription(
        key="restricted",
        translation_key="profile_restricted",
        value_key="restricted",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge switches."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_setup_profile_entities(
        runtime,
        entry,
        async_add_entities,
        PROFILE_SWITCHES,
        AndroidTVBridgeProfileRestrictedSwitch,
    )


class AndroidTVBridgeProfileRestrictedSwitch(AndroidTVBridgeProfileEntity, SwitchEntity):
    """Whether a profile is restricted (a kids profile)."""

    entity_description: AndroidTVBridgeProfileSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Return whether the profile is restricted."""
        value = self.profile_value
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Restrict the profile."""
        await self.async_send_profile_command(
            "set_profile_restricted", {"restricted": True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Lift the restriction."""
        await self.async_send_profile_command(
            "set_profile_restricted", {"restricted": False}
        )
