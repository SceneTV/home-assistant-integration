"""Notify entities for Android TV Bridge."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AndroidTVBridgeEntity
from .runtime import AndroidTVBridgeRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge notify entities."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AndroidTVBridgeNotify(runtime)])


class AndroidTVBridgeNotify(AndroidTVBridgeEntity, NotifyEntity):
    """Notify entity that shows SceneTV text popups."""

    def __init__(self, runtime: AndroidTVBridgeRuntime) -> None:
        """Initialize the notify entity."""
        super().__init__(
            runtime,
            EntityDescription(
                key="notify_popup",
                translation_key="popup",
            ),
        )

    async def async_send_message(
        self,
        message: str,
        title: str | None = None,
    ) -> None:
        """Send a Home Assistant notification as a SceneTV popup."""
        await self.runtime.async_send_command(
            "show_popup",
            {
                "message": message,
                **({"title": title} if title else {}),
            },
        )
        self._async_record_notification()
