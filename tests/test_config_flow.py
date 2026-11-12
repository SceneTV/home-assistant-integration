"""Tests for the config flow: pairing, reauth and reconfigure."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.android_tv_bridge.client import (
    AndroidTVBridgeAuthError,
    AndroidTVBridgeConnectionError,
)
from custom_components.android_tv_bridge.remote_v2 import RemoteV2InvalidCode
from custom_components.android_tv_bridge.const import (
    CONF_API_VERSION,
    CONF_TOKEN,
    DOMAIN,
)

CLIENT = "custom_components.android_tv_bridge.config_flow.AndroidTVBridgeClient"
METADATA = {"device_id": "launcher-1", "display_name": "Living Room TV"}
ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 8765,
    CONF_NAME: "Living Room TV",
    CONF_TOKEN: "old-token",
    CONF_API_VERSION: "v1",
}


@pytest.fixture
def mock_setup_entry():
    """Keep the real integration from starting when a flow creates an entry."""
    with patch(
        "custom_components.android_tv_bridge.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def client():
    """Patch the launcher client used by the config flow."""
    with patch(CLIENT) as cls:
        instance = cls.return_value
        instance.async_get_metadata = AsyncMock(return_value=METADATA)
        instance.async_link_pairing = AsyncMock(return_value={"token": "new-token"})
        yield instance


REMOTE = "custom_components.android_tv_bridge.config_flow.RemoteV2Pairing"


@pytest.fixture
def remote():
    """Patch the Remote v2 pairing; by default the TV asks for a code."""
    with patch(REMOTE) as cls:
        instance = cls.return_value
        instance.async_start = AsyncMock(return_value=True)
        instance.async_finish = AsyncMock()
        instance.async_send_link = AsyncMock()
        instance.close = MagicMock()
        yield instance


@pytest.fixture(autouse=True)
def fast_link_retry():
    with patch("custom_components.android_tv_bridge.config_flow.LINK_RETRY_SECONDS", 0):
        yield


async def _to_code_step(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.0.2.10", CONF_PORT: 8765, CONF_NAME: "SceneTV"},
    )


async def test_user_flow_pairs_with_code_and_creates_entry(
    hass: HomeAssistant, client, remote, mock_setup_entry
) -> None:
    result = await _to_code_step(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "1a2b3c"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room TV"
    assert result["data"][CONF_TOKEN] == "new-token"
    assert result["result"].unique_id == "launcher-1"
    remote.async_finish.assert_awaited_once_with("1A2B3C")
    remote.close.assert_called()
    # The nonce in the link is the one traded for the token.
    link = remote.async_send_link.await_args.args[0]
    nonce = client.async_link_pairing.await_args.kwargs["nonce"]
    assert link.startswith("scenetv://pair?n=" + nonce + "&c=")
    assert client.async_link_pairing.await_args.kwargs["ha_instance_id"] in link


async def test_user_flow_wrong_code_shows_error(
    hass: HomeAssistant, client, remote, mock_setup_entry
) -> None:
    remote.async_finish.side_effect = RemoteV2InvalidCode("wrong")
    result = await _to_code_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "AAAAAA"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "invalid_code"}
    client.async_link_pairing.assert_not_awaited()


async def test_user_flow_malformed_code_never_reaches_tv(
    hass: HomeAssistant, client, remote, mock_setup_entry
) -> None:
    result = await _to_code_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "12"}
    )
    assert result["errors"] == {"base": "invalid_code"}
    remote.async_finish.assert_not_awaited()


async def test_user_flow_already_paired_skips_code(
    hass: HomeAssistant, client, remote, mock_setup_entry
) -> None:
    remote.async_start.return_value = False
    result = await _to_code_step(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TOKEN] == "new-token"


async def test_user_flow_waits_for_launcher_to_receive_link(
    hass: HomeAssistant, client, remote, mock_setup_entry
) -> None:
    client.async_link_pairing.side_effect = [
        AndroidTVBridgeAuthError("not yet"),
        AndroidTVBridgeAuthError("not yet"),
        {"token": "new-token"},
    ]
    result = await _to_code_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "1A2B3C"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert client.async_link_pairing.await_count == 3


async def test_user_flow_aborts_when_launcher_never_gets_link(
    hass: HomeAssistant, client, remote, mock_setup_entry
) -> None:
    client.async_link_pairing.side_effect = AndroidTVBridgeAuthError("no")
    with patch(
        "custom_components.android_tv_bridge.config_flow.LINK_MAX_WAIT_SECONDS", 0
    ):
        result = await _to_code_step(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "1A2B3C"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "link_failed"
    remote.close.assert_called()


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    client.async_get_metadata.side_effect = AndroidTVBridgeConnectionError("down")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.0.2.10", CONF_PORT: 8765, CONF_NAME: "SceneTV"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA).add_to_hass(
        hass
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.0.2.10", CONF_PORT: 8765, CONF_NAME: "SceneTV"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _start_reauth(hass: HomeAssistant, entry: MockConfigEntry):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=dict(entry.data),
    )


async def test_reauth_repairs_and_updates_token(
    hass: HomeAssistant, client, remote, mock_setup_entry
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await _start_reauth(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "1A2B3C"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "new-token"
    assert entry.data[CONF_HOST] == "192.0.2.10"


async def test_reauth_cannot_connect_shows_error(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    client.async_get_metadata.side_effect = AndroidTVBridgeConnectionError("down")

    result = await _start_reauth(hass, entry)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_TOKEN] == "old-token"


async def test_reauth_aborts_when_address_is_another_launcher(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    client.async_get_metadata.return_value = {"device_id": "launcher-2"}

    result = await _start_reauth(hass, entry)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_TOKEN] == "old-token"
    client.async_request_pairing.assert_not_called()


async def _start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )


async def test_reconfigure_updates_host(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await _start_reconfigure(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.20", CONF_PORT: 8766}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.0.2.20"
    assert entry.data[CONF_PORT] == 8766
    assert entry.data[CONF_TOKEN] == "old-token"


async def test_reconfigure_rejects_other_launcher(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    client.async_get_metadata.return_value = {"device_id": "launcher-2"}

    result = await _start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.20", CONF_PORT: 8765}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "192.0.2.10"
