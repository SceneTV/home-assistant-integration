"""Number entities for Android TV Bridge (per-profile daily screen time budget)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .parental import (
    AndroidTVBridgeProfileEntity,
    ProfileEntityDescription,
    async_setup_profile_entities,
)
from .runtime import AndroidTVBridgeRuntime

MAX_DAILY_BUDGET_MIN = 1440


@dataclass(frozen=True, kw_only=True)
class AndroidTVBridgeProfileNumberDescription(
    ProfileEntityDescription, NumberEntityDescription
):
    """Describes a per-profile number."""


PROFILE_NUMBERS: tuple[AndroidTVBridgeProfileNumberDescription, ...] = (
    AndroidTVBridgeProfileNumberDescription(
        key="daily_budget",
        translation_key="profile_daily_budget",
        value_key="daily_budget_min",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=0,
        native_max_value=MAX_DAILY_BUDGET_MIN,
        native_step=1,
        mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Android TV Bridge number entities."""
    runtime: AndroidTVBridgeRuntime = hass.data[DOMAIN][entry.entry_id]
    async_setup_profile_entities(
        runtime,
        entry,
        async_add_entities,
        PROFILE_NUMBERS,
        AndroidTVBridgeProfileBudgetNumber,
    )


class AndroidTVBridgeProfileBudgetNumber(AndroidTVBridgeProfileEntity, NumberEntity):
    """Daily screen time budget of one profile.

    The state is unknown while the profile has no limit; use the
    set_profile_policy action with clear_daily_budget to remove a limit.
    """

    entity_description: AndroidTVBridgeProfileNumberDescription

    @property
    def native_value(self) -> float | None:
        """Return the budget in minutes, or None for no limit."""
        value = self.profile_value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value

    async def async_set_native_value(self, value: float) -> None:
        """Set the daily budget."""
        await self.async_send_profile_command(
            "set_profile_policy", {"daily_budget_min": int(value)}
        )
