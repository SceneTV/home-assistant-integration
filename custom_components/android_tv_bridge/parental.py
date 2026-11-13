"""Per-profile parental control entities (launcher issue #34).

The launcher lists its profiles in state ``profiles[]``. Launchers with the
kids profile work add per-profile fields to those entries (``restricted``,
``screen_time_today_min``, ``daily_budget_min`` and so on). Each platform
creates one entity per profile and field, as soon as a profile entry carries
that field. Older launchers never send the fields, so the entities are simply
not created; a field or profile that disappears later makes its entity
unavailable rather than removing it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import AndroidTVBridgeEntity
from .runtime import AndroidTVBridgeRuntime


@dataclass(frozen=True, kw_only=True)
class ProfileEntityDescription(EntityDescription):
    """Describes one per-profile entity backed by a ``profiles[]`` field."""

    value_key: str


def profile_entries(data: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """Return the launcher's profile entries that carry an id."""
    profiles = (data or {}).get("profiles")
    if not isinstance(profiles, list):
        return []
    return [
        profile
        for profile in profiles
        if isinstance(profile, Mapping) and profile.get("id") is not None
    ]


def find_profile(
    data: Mapping[str, Any] | None, profile_id: Any
) -> Mapping[str, Any] | None:
    """Return the profile entry with this id, if the launcher still lists it."""
    wanted = str(profile_id)
    for profile in profile_entries(data):
        if str(profile.get("id")) == wanted:
            return profile
    return None


def async_setup_profile_entities(
    runtime: AndroidTVBridgeRuntime,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    descriptions: Iterable[ProfileEntityDescription],
    factory: Callable[
        [AndroidTVBridgeRuntime, ProfileEntityDescription, Mapping[str, Any]],
        Entity,
    ],
) -> None:
    """Add per-profile entities now and whenever a new profile or field appears."""
    descriptions = tuple(descriptions)
    added: set[tuple[str, str]] = set()

    @callback
    def _add_new() -> None:
        new: list[Entity] = []
        for profile in profile_entries(runtime.coordinator.data):
            profile_id = str(profile["id"])
            for description in descriptions:
                marker = (profile_id, description.key)
                if marker in added or description.value_key not in profile:
                    continue
                added.add(marker)
                new.append(factory(runtime, description, profile))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(runtime.coordinator.async_add_listener(_add_new))


class AndroidTVBridgeProfileEntity(AndroidTVBridgeEntity):
    """Entity for one field of one launcher profile."""

    entity_description: ProfileEntityDescription

    def __init__(
        self,
        runtime: AndroidTVBridgeRuntime,
        description: ProfileEntityDescription,
        profile: Mapping[str, Any],
    ) -> None:
        """Initialize the entity for a profile."""
        super().__init__(runtime, description)
        self.profile_id = profile["id"]
        self._attr_unique_id = (
            f"{runtime.device_id}_profile_{self.profile_id}_{description.key}"
        )
        self._attr_translation_placeholders = {
            "profile": str(profile.get("name") or self.profile_id)
        }

    @property
    def profile(self) -> Mapping[str, Any] | None:
        """Return this entity's profile entry from the latest state."""
        return find_profile(self.coordinator.data, self.profile_id)

    @property
    def available(self) -> bool:
        """Unavailable when the profile or its field is gone from state."""
        profile = self.profile
        return (
            super().available
            and profile is not None
            and self.entity_description.value_key in profile
        )

    @property
    def profile_value(self) -> Any:
        """Return this entity's field from the profile entry."""
        profile = self.profile
        if profile is None:
            return None
        return profile.get(self.entity_description.value_key)

    async def async_send_profile_command(
        self, command_type: str, payload: Mapping[str, Any]
    ) -> None:
        """Send a profile command for this entity's profile."""
        await self.runtime.async_send_command(
            command_type, {"profile_id": self.profile_id, **payload}
        )


def parse_hhmm(value: Any) -> time | None:
    """Parse a launcher "HH:MM" local time; None for null or bad input."""
    if not isinstance(value, str):
        return None
    try:
        hours, minutes = value.strip().split(":")[:2]
        return time(int(hours), int(minutes))
    except ValueError:
        return None
