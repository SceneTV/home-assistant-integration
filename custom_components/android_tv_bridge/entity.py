"""Base entity helpers for Android TV Bridge."""

from __future__ import annotations

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .runtime import AndroidTVBridgeRuntime


class AndroidTVBridgeEntity(CoordinatorEntity):
    """Base entity for one Android TV Bridge runtime."""

    _attr_has_entity_name = True

    def __init__(
        self,
        runtime: AndroidTVBridgeRuntime,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self.entity_description = description
        self._attr_unique_id = f"{runtime.device_id}_{description.key}"
        self._attr_device_info = runtime.device_info

    @property
    def available(self) -> bool:
        """Return whether the launcher is reachable.

        Commands and live state both ride the WebSocket, so entities go
        unavailable while it is down, even if HTTP polling still answers.
        """
        return self.coordinator.last_update_success and self.runtime.connected


def prefixed_translation_key(key: str) -> str:
    """Return a stable entity translation key."""
    return f"{DOMAIN}_{key}"
