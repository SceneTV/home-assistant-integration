"""Select entities for Android TV Bridge."""

from __future__ import annotations

from collections.abc import Mapping

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AndroidTVBridgeEntity
from .runtime import AndroidTVBridgeRuntime

# Matches LAUNCHER_MODES in the launcher; used only if state omits the list.
_FALLBACK_MODES = ["default", "focus", "ambient"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge select entities."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AndroidTVBridgeModeSelect(
                runtime,
                SelectEntityDescription(
                    key="launcher_mode",
                    translation_key="launcher_mode",
                ),
            ),
            AndroidTVBridgeProfileSelect(
                runtime,
                SelectEntityDescription(
                    key="active_profile",
                    translation_key="active_profile",
                ),
            ),
        ]
    )


class AndroidTVBridgeModeSelect(AndroidTVBridgeEntity, SelectEntity):
    """Select the launcher mode."""

    @property
    def options(self) -> list[str]:
        """Return supported launcher modes."""
        modes = (self.coordinator.data or {}).get("launcher_modes")
        if isinstance(modes, list) and all(isinstance(mode, str) for mode in modes):
            return modes
        return _FALLBACK_MODES

    @property
    def current_option(self) -> str | None:
        """Return the current launcher mode."""
        mode = (self.coordinator.data or {}).get("launcher_mode")
        return str(mode) if mode is not None else None

    async def async_select_option(self, option: str) -> None:
        """Set the launcher mode."""
        await self.runtime.async_send_command(
            "set_launcher_mode",
            {"mode": option},
        )


class AndroidTVBridgeProfileSelect(AndroidTVBridgeEntity, SelectEntity):
    """Select the active launcher profile."""

    @property
    def options(self) -> list[str]:
        """Return supported launcher profiles."""
        data = self.coordinator.data or {}
        options = data.get("profile_options")
        if isinstance(options, list) and all(
            isinstance(profile, str) for profile in options
        ):
            return options

        profiles = data.get("profiles")
        if isinstance(profiles, list):
            names = [
                str(profile.get("name"))
                for profile in profiles
                if isinstance(profile, Mapping) and profile.get("name") is not None
            ]
            if names:
                return names
        return []

    @property
    def current_option(self) -> str | None:
        """Return the current active launcher profile."""
        profile = (self.coordinator.data or {}).get("active_profile")
        return str(profile) if profile is not None else None

    async def async_select_option(self, option: str) -> None:
        """Set the active launcher profile."""
        await self.runtime.async_send_command(
            "select_profile",
            {"profile": option},
        )
