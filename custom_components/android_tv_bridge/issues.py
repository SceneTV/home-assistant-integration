"""Repair issues raised from launcher state.

The launcher reports permission and setting flags in its state. When one of
them blocks a feature, a Repairs issue tells the user what to change on the TV.
The issue clears itself as soon as the launcher reports the flag as fixed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


@dataclass(frozen=True)
class StateIssue:
    """A Repairs issue driven by one boolean launcher state key."""

    key: str
    state_key: str
    severity: ir.IssueSeverity = ir.IssueSeverity.WARNING


STATE_ISSUES: tuple[StateIssue, ...] = (
    StateIssue(key="accessibility_disabled", state_key="accessibility_enabled"),
    StateIssue(key="overlay_permission_missing", state_key="overlay_permission"),
)


def issue_id(entry: ConfigEntry, issue: StateIssue) -> str:
    """Return the issue id for one config entry."""
    return f"{issue.key}_{entry.entry_id}"


@callback
def async_update_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
    name: str,
    state: Mapping[str, Any],
) -> None:
    """Create or clear Repairs issues from a launcher state snapshot.

    Only an explicit ``False`` raises an issue. A missing key (older launcher,
    or state not received yet) leaves the current issue untouched.
    """
    for issue in STATE_ISSUES:
        value = state.get(issue.state_key)
        if value is None:
            continue
        if value is False:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id(entry, issue),
                is_fixable=False,
                is_persistent=False,
                severity=issue.severity,
                translation_key=issue.key,
                translation_placeholders={"name": name},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id(entry, issue))


@callback
def async_clear_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove every Repairs issue owned by a config entry."""
    for issue in STATE_ISSUES:
        ir.async_delete_issue(hass, DOMAIN, issue_id(entry, issue))
