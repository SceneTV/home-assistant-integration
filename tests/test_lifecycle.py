"""Tests for entry setup/reload and WebSocket lifecycle."""

from __future__ import annotations

from unittest.mock import patch

from aiohttp import WSMsgType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.android_tv_bridge.const import DOMAIN
from custom_components.android_tv_bridge.runtime import AndroidTVBridgeRuntime


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="launcher-1",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
    )


async def test_reload_does_not_stack_update_listeners(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    async def fake_start(self: AndroidTVBridgeRuntime) -> None:
        self.metadata = {"device_id": "launcher-1", "display_name": "TV"}
        self.connected = True
        self._ws_task = hass.async_create_task(_forever())

    async def _forever() -> None:
        import asyncio

        await asyncio.Event().wait()

    with patch.object(AndroidTVBridgeRuntime, "async_start", fake_start):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.LOADED
        for _ in range(2):
            assert await hass.config_entries.async_reload(entry.entry_id)
            assert entry.state is ConfigEntryState.LOADED
        assert len(entry.update_listeners) == 0
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


class _Message:
    def __init__(self, type_: WSMsgType) -> None:
        self.type = type_


class _ClosingSocket:
    """WebSocket that ends cleanly, like a launcher closing the connection."""

    closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


async def test_clean_websocket_close_marks_disconnected(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    runtime = AndroidTVBridgeRuntime(hass, entry)
    states: list[bool] = []
    original = runtime._merge_state

    def record(update):
        original(update)
        if "connection" in update:
            states.append(update["connection"])

    async def open_ws():
        return _ClosingSocket()

    async def stop_after_sleep(_delay):
        runtime._stopped.set()

    with (
        patch.object(runtime.client, "async_open_websocket", open_ws),
        patch.object(runtime, "_merge_state", record),
        patch("custom_components.android_tv_bridge.runtime.asyncio.sleep", stop_after_sleep),
    ):
        await runtime._async_listen()

    assert states == [True, False]
    assert runtime.connected is False


async def test_send_failure_does_not_leak_pending(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    runtime = AndroidTVBridgeRuntime(hass, entry)
    runtime.connected = True

    class BrokenSocket:
        closed = False

        async def send_json(self, _data):
            raise ConnectionResetError("gone")

    runtime._ws_task = object()  # type: ignore[assignment]
    runtime._websocket = BrokenSocket()  # type: ignore[assignment]
    with pytest.raises(HomeAssistantError):
        await runtime.async_send_command("launch_app", {"package": "x"})
    assert runtime._pending == {}
