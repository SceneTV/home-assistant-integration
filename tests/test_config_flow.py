"""Tests for the config flow: pairing, reauth and reconfigure."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.android_tv_bridge.client import (
    AndroidTVBridgeConnectionError,
)
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
        instance.async_request_pairing = AsyncMock(
            return_value={"status": "pending", "request_id": "req-1"}
        )
        instance.async_get_pairing_status = AsyncMock(
            return_value={"status": "approved", "token": "new-token"}
        )
        yield instance


async def test_user_flow_pairs_and_creates_entry(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.0.2.10", CONF_PORT: 8765, CONF_NAME: "SceneTV"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room TV"
    assert result["data"][CONF_TOKEN] == "new-token"
    assert result["result"].unique_id == "launcher-1"


async def test_user_flow_pairing_still_pending(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    client.async_get_pairing_status.return_value = {"status": "pending"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.0.2.10", CONF_PORT: 8765, CONF_NAME: "SceneTV"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "pairing_pending"}


async def test_user_flow_rejected_on_tv(
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    client.async_get_pairing_status.return_value = {"status": "rejected"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.0.2.10", CONF_PORT: 8765, CONF_NAME: "SceneTV"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "pairing_rejected"


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
    hass: HomeAssistant, client, mock_setup_entry
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="launcher-1", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await _start_reauth(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
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
