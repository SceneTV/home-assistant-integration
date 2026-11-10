"""Tests for the Remote v2 pairing wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from androidtvremote2 import InvalidAuth
import pytest

from homeassistant.core import HomeAssistant

from custom_components.android_tv_bridge.remote_v2 import (
    RemoteV2InvalidCode,
    RemoteV2Pairing,
    pair_link,
)

LIB = "custom_components.android_tv_bridge.remote_v2.AndroidTVRemote"


@pytest.fixture
def lib():
    with patch(LIB) as cls:
        inst = cls.return_value
        inst.async_generate_cert_if_missing = AsyncMock()
        inst.async_connect = AsyncMock()
        inst.async_start_pairing = AsyncMock()
        inst.async_finish_pairing = AsyncMock()
        inst.send_launch_app_command = MagicMock()
        yield inst


def test_pair_link_escapes_values() -> None:
    assert pair_link("abc_-", "ha id/1") == "scenetv://pair?n=abc_-&c=ha%20id%2F1"


async def test_already_paired_needs_no_code(hass: HomeAssistant, lib) -> None:
    assert await RemoteV2Pairing(hass, "192.0.2.10").async_start() is False
    lib.async_start_pairing.assert_not_awaited()


async def test_unpaired_starts_pairing(hass: HomeAssistant, lib) -> None:
    lib.async_connect.side_effect = InvalidAuth
    assert await RemoteV2Pairing(hass, "192.0.2.10").async_start() is True
    lib.async_start_pairing.assert_awaited_once()


async def test_wrong_code_restarts_pairing(hass: HomeAssistant, lib) -> None:
    lib.async_finish_pairing.side_effect = InvalidAuth
    pairing = RemoteV2Pairing(hass, "192.0.2.10")
    with pytest.raises(RemoteV2InvalidCode):
        await pairing.async_finish("AAAAAA")
    lib.async_start_pairing.assert_awaited_once()
