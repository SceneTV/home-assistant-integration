"""Tests for diagnostics, repairs, availability and mid-session reauth."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.android_tv_bridge.binary_sensor import (
    BINARY_SENSORS,
    AndroidTVBridgeBinarySensor,
)
from custom_components.android_tv_bridge.client import AndroidTVBridgeAuthError
from custom_components.android_tv_bridge.const import CONF_TOKEN, DOMAIN
from custom_components.android_tv_bridge.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.android_tv_bridge.issues import (
    async_clear_issues,
    async_update_issues,
)
from custom_components.android_tv_bridge.runtime import AndroidTVBridgeRuntime

ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 8765,
    CONF_NAME: "Living Room TV",
    CONF_TOKEN: "secret-token",
}


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    return entry


async def test_diagnostics_redacts_token_and_addresses(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    coordinator = DataUpdateCoordinator(
        hass, logging.getLogger(__name__), config_entry=entry, name="t"
    )
    coordinator.data = {
        "media_title": "Show",
        "network": {"type": "wifi", "ip_address": "192.0.2.10"},
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        connected=True,
        coordinator=coordinator,
        metadata={"device_id": "launcher-1", "mac_address": "aa:bb:cc:dd:ee:ff"},
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"]["data"][CONF_TOKEN] == "**REDACTED**"
    assert diag["entry"]["data"][CONF_HOST] == "**REDACTED**"
    assert diag["entry"]["data"][CONF_PORT] == 8765
    assert diag["runtime"]["connected"] is True
    assert diag["runtime"]["metadata"]["mac_address"] == "**REDACTED**"
    assert diag["runtime"]["metadata"]["device_id"] == "launcher-1"
    assert diag["runtime"]["state"]["network"]["ip_address"] == "**REDACTED**"
    assert diag["runtime"]["state"]["media_title"] == "Show"
    assert "secret-token" not in repr(diag)


async def test_diagnostics_without_runtime(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["runtime"] is None
    assert diag["entry"]["data"][CONF_TOKEN] == "**REDACTED**"


async def test_repairs_follow_launcher_state(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    registry = ir.async_get(hass)
    accessibility_id = f"accessibility_disabled_{entry.entry_id}"
    overlay_id = f"overlay_permission_missing_{entry.entry_id}"

    async_update_issues(
        hass,
        entry,
        "Living Room TV",
        {"accessibility_enabled": False, "overlay_permission": True},
    )
    issue = registry.async_get_issue(DOMAIN, accessibility_id)
    assert issue is not None
    assert issue.translation_placeholders == {"name": "Living Room TV"}
    assert registry.async_get_issue(DOMAIN, overlay_id) is None

    # A state without the key (older launcher) leaves the issue alone.
    async_update_issues(hass, entry, "Living Room TV", {})
    assert registry.async_get_issue(DOMAIN, accessibility_id) is not None

    async_update_issues(
        hass,
        entry,
        "Living Room TV",
        {"accessibility_enabled": True, "overlay_permission": False},
    )
    assert registry.async_get_issue(DOMAIN, accessibility_id) is None
    assert registry.async_get_issue(DOMAIN, overlay_id) is not None

    async_clear_issues(hass, entry)
    assert registry.async_get_issue(DOMAIN, overlay_id) is None


def _binary_sensor(hass: HomeAssistant, key: str, connected: bool):
    coordinator = DataUpdateCoordinator(
        hass, logging.getLogger(__name__), config_entry=_entry(hass), name="t"
    )
    coordinator.data = {"connection": connected, "playing": True}
    coordinator.last_update_success = True
    runtime = SimpleNamespace(
        coordinator=coordinator,
        connected=connected,
        device_id="launcher-1",
        device_info={"identifiers": {(DOMAIN, "launcher-1")}},
    )
    description = next(d for d in BINARY_SENSORS if d.key == key)
    return AndroidTVBridgeBinarySensor(runtime, description)


async def test_entities_unavailable_while_websocket_down(hass: HomeAssistant) -> None:
    assert _binary_sensor(hass, "playing", connected=True).available is True
    assert _binary_sensor(hass, "playing", connected=False).available is False


async def test_connection_sensor_stays_available(hass: HomeAssistant) -> None:
    sensor = _binary_sensor(hass, "connection", connected=False)
    assert sensor.available is True
    assert sensor.is_on is False


async def test_dead_entities_disabled_by_default() -> None:
    idle = next(d for d in BINARY_SENSORS if d.key == "idle")
    assert idle.entity_registry_enabled_default is False
    assert isinstance(idle, BinarySensorEntityDescription)


async def test_token_rejected_mid_session_starts_reauth(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    runtime = AndroidTVBridgeRuntime(hass, entry)
    runtime.client.async_open_websocket = AsyncMock(
        side_effect=AndroidTVBridgeAuthError("rejected")
    )
    with patch.object(entry, "async_start_reauth") as start_reauth:
        await runtime._async_listen()
    start_reauth.assert_called_once_with(hass)
    assert runtime.connected is False
