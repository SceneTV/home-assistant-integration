"""Shared fixtures for SceneTV Android TV Bridge tests."""

from __future__ import annotations

from typing import Any

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let Home Assistant load the custom integration in every test."""


class FakeRuntime:
    """Records commands instead of talking to a launcher."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.device_name = name
        self.fail = fail
        self.commands: list[tuple[str, dict[str, Any], int | None]] = []

    async def async_send_command(
        self,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        from homeassistant.exceptions import HomeAssistantError

        self.commands.append((command_type, dict(payload or {}), timeout_ms))
        if self.fail:
            raise HomeAssistantError("Launcher WebSocket is not connected")
        return {"status": "succeeded"}
