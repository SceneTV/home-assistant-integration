"""Home Assistant integration for SceneTV Android TV launchers."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .client import AndroidTVBridgeAuthError, AndroidTVBridgeError
from .const import DOMAIN, PLATFORMS
from .runtime import AndroidTVBridgeRuntime
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Android TV Bridge from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    runtime = AndroidTVBridgeRuntime(hass, entry)

    try:
        await runtime.async_start()
    except AndroidTVBridgeAuthError as err:
        raise ConfigEntryAuthFailed("Stored pairing token was rejected") from err
    except AndroidTVBridgeError as err:
        raise ConfigEntryNotReady(
            f"Could not connect to launcher at {entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"
        ) from err

    hass.data[DOMAIN][entry.entry_id] = runtime
    async_register_services(hass)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await runtime.async_stop()
        raise
    # Options (exposed scripts/scenes) only need a fresh catalog on the launcher,
    # not a reload. Registered with async_on_unload so reloads never stack it.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Push the updated action catalog to the launcher."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is not None:
        await runtime.async_push_action_catalog()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Android TV Bridge config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime: AndroidTVBridgeRuntime | None = hass.data[DOMAIN].pop(
            entry.entry_id, None
        )
        if runtime is not None:
            await runtime.async_stop()
        if not hass.data[DOMAIN]:
            async_unregister_services(hass)
    return unload_ok
