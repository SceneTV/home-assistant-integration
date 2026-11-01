"""Diagnostics support for SceneTV Android TV Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, DOMAIN
from .runtime import AndroidTVBridgeRuntime

TO_REDACT = {
    CONF_TOKEN,
    CONF_HOST,
    "ip",
    "ip_address",
    "ipAddress",
    "addresses",
    "mac",
    "mac_address",
    "macAddress",
    "serial",
    "serial_number",
    "serialNumber",
    "android_id",
    "androidId",
    "ssid",
    "wifi_ssid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with secrets and addresses redacted."""
    runtime: AndroidTVBridgeRuntime | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    diagnostics: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
    }
    if runtime is None:
        diagnostics["runtime"] = None
        return diagnostics

    diagnostics["runtime"] = {
        "connected": runtime.connected,
        "last_update_success": runtime.coordinator.last_update_success,
        "metadata": async_redact_data(runtime.metadata, TO_REDACT),
        "state": async_redact_data(runtime.coordinator.data or {}, TO_REDACT),
    }
    return diagnostics
