"""Config flow for Android TV Bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import secrets
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import instance_id, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import (
    AndroidTVBridgeAuthError,
    AndroidTVBridgeClient,
    AndroidTVBridgeError,
)
from .const import (
    CONF_API_VERSION,
    CONF_EXPOSED_ACTIONS,
    CONF_TOKEN,
    DEFAULT_API_VERSION,
    DEFAULT_PORT,
    DOMAIN,
    EXPOSED_ACTION_DOMAINS,
)

from .remote_v2 import RemoteV2InvalidCode, RemoteV2Pairing, pair_link

_LOGGER = logging.getLogger(__name__)

# The launcher receives the link asynchronously, so the nonce may not be known yet.
LINK_RETRY_SECONDS = 0.4
LINK_MAX_WAIT_SECONDS = 6.0
_CODE_LENGTH = 6

_STABLE_ID_KEYS = (
    "device_id",
    "deviceId",
    "android_id",
    "androidId",
    "installation_id",
    "installationId",
    "uuid",
    "serial_number",
    "serialNumber",
    "serial",
    "mac_address",
    "macAddress",
)
_STABLE_DISCOVERY_KEYS = (*_STABLE_ID_KEYS, "hostname", "server")


def _property(properties: dict[str, Any], key: str) -> str | None:
    value = properties.get(key)
    if isinstance(value, bytes):
        return value.decode(errors="ignore")
    if value is None:
        return None
    return str(value)


def _metadata_value(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    return str(value)


def _stable_unique_id(
    metadata: dict[str, Any],
    discovery_properties: dict[str, Any] | None = None,
) -> str | None:
    """Return the most stable launcher identifier available."""
    for key in _STABLE_ID_KEYS:
        if value := _metadata_value(metadata, key):
            return value

    if discovery_properties:
        for key in _STABLE_DISCOVERY_KEYS:
            if value := _property(discovery_properties, key):
                return value

    return None


class AndroidTVBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an Android TV Bridge config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._name: str = "SceneTV"
        self._api_version: str = DEFAULT_API_VERSION
        self._metadata: dict[str, Any] = {}
        self._discovery_properties: dict[str, Any] = {}
        self._remote: RemoteV2Pairing | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input[CONF_PORT]
            self._name = user_input[CONF_NAME]
            try:
                await self._async_fetch_metadata()
                return await self._async_start_pairing()
            except AndroidTVBridgeError:
                _LOGGER.exception("Could not start pairing")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Required(CONF_NAME, default="SceneTV"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: Any
    ) -> config_entries.ConfigFlowResult:
        """Handle Zeroconf discovery."""
        self._host = discovery_info.host
        self._port = discovery_info.port or DEFAULT_PORT
        properties = dict(discovery_info.properties or {})
        if hostname := getattr(discovery_info, "hostname", None):
            properties.setdefault("hostname", hostname)
        self._name = (
            _property(properties, "display_name")
            or _property(properties, "name")
            or discovery_info.name
            or "SceneTV"
        )
        self.context["title_placeholders"] = {"name": self._name}
        self._discovery_properties = properties

        unique_id = _stable_unique_id({}, properties)
        if unique_id:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host, CONF_PORT: self._port}
            )

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm a discovered launcher before prompting the TV."""
        if user_input is not None:
            try:
                await self._async_fetch_metadata()
                return await self._async_start_pairing()
            except AndroidTVBridgeError:
                _LOGGER.exception("Could not start discovered pairing")
                return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": self._name},
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Enter the code the TV's Android TV Remote service shows."""
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input["code"]).strip().upper()
            if len(code) != _CODE_LENGTH:
                errors["base"] = "invalid_code"
            else:
                assert self._remote is not None
                try:
                    await self._remote.async_finish(code)
                except RemoteV2InvalidCode:
                    errors["base"] = "invalid_code"
                except AndroidTVBridgeError:
                    _LOGGER.exception("Remote v2 pairing failed")
                    errors["base"] = "cannot_connect"
                else:
                    return await self._async_link_and_create()

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required("code"): str}),
            description_placeholders={"name": self._name},
            errors=errors,
        )

    async def _async_fetch_metadata(self) -> None:
        assert self._host is not None
        client = AndroidTVBridgeClient(
            async_get_clientsession(self.hass),
            self._host,
            self._port,
            api_version=self._api_version,
        )
        self._metadata = await client.async_get_metadata()
        if self._reauth_entry is not None:
            # Never hand a token for this entry to a different launcher that
            # took over the stored address.
            found = _stable_unique_id(self._metadata)
            expected = self._reauth_entry.unique_id
            if expected and found and found != expected:
                raise AbortFlow("wrong_device")
            return
        unique_id = _stable_unique_id(self._metadata, self._discovery_properties)
        if unique_id:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host, CONF_PORT: self._port}
            )
        self._name = str(
            self._metadata.get("display_name") or self._metadata.get("name") or self._name
        )

    async def _async_start_pairing(self) -> config_entries.ConfigFlowResult:
        """Start Remote v2 pairing; the code the user types is the only approval."""
        assert self._host is not None
        self._close_remote()
        self._remote = RemoteV2Pairing(self.hass, self._host)
        if await self._remote.async_start():
            return await self.async_step_pair()
        return await self._async_link_and_create()

    async def _async_link_and_create(self) -> config_entries.ConfigFlowResult:
        """Prove the Remote v2 pairing to the launcher and store its token."""
        assert self._host is not None
        assert self._remote is not None
        client = AndroidTVBridgeClient(
            async_get_clientsession(self.hass),
            self._host,
            self._port,
            api_version=self._api_version,
        )
        ha_instance_id = await instance_id.async_get(self.hass)
        nonce = secrets.token_urlsafe(16)
        try:
            await self._remote.async_send_link(pair_link(nonce, ha_instance_id))
            waited = 0.0
            while True:
                try:
                    response = await client.async_link_pairing(
                        ha_instance_id=ha_instance_id,
                        ha_name=self.hass.config.location_name,
                        nonce=nonce,
                    )
                    break
                except AndroidTVBridgeAuthError:
                    # 403 until the launcher has seen the link; the nonce is not spent.
                    if waited >= LINK_MAX_WAIT_SECONDS:
                        raise AndroidTVBridgeError(
                            "The launcher did not receive the pairing link"
                        ) from None
                    await asyncio.sleep(LINK_RETRY_SECONDS)
                    waited += LINK_RETRY_SECONDS
        except AndroidTVBridgeError:
            _LOGGER.exception("Could not link Home Assistant to the launcher")
            return self.async_abort(reason="link_failed")
        finally:
            self._close_remote()
        if not response.get("token"):
            return self.async_abort(reason="link_failed")
        return await self._async_create_entry(str(response["token"]))

    def _close_remote(self) -> None:
        if self._remote is not None:
            self._remote.close()
            self._remote = None

    @callback
    def async_remove(self) -> None:
        """Release the TV connection if the flow is abandoned."""
        self._close_remote()

    async def _async_create_entry(self, token: str) -> config_entries.ConfigFlowResult:
        assert self._host is not None
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data={**self._reauth_entry.data, CONF_TOKEN: token},
                reason="reauth_successful",
            )
        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_NAME: self._name,
            CONF_TOKEN: token,
            CONF_API_VERSION: self._api_version,
        }
        return self.async_create_entry(title=self._name, data=data)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start reauthentication after the launcher rejected the stored token."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._host = entry_data[CONF_HOST]
        self._port = entry_data[CONF_PORT]
        self._name = entry_data.get(CONF_NAME) or self._name
        self._api_version = entry_data.get(CONF_API_VERSION, DEFAULT_API_VERSION)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pair again through the TV's Android TV Remote service."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._async_fetch_metadata()
                return await self._async_start_pairing()
            except AndroidTVBridgeError:
                _LOGGER.exception("Could not start re-pairing")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"name": self._name},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change the host or port of an existing launcher."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            client = AndroidTVBridgeClient(
                async_get_clientsession(self.hass),
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                api_version=entry.data.get(CONF_API_VERSION, DEFAULT_API_VERSION),
            )
            try:
                metadata = await client.async_get_metadata()
            except AndroidTVBridgeError:
                errors["base"] = "cannot_connect"
            else:
                unique_id = _stable_unique_id(metadata)
                if entry.unique_id and unique_id and unique_id != entry.unique_id:
                    return self.async_abort(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                    },
                    reason="reconfigure_successful",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST, "")
                    ): str,
                    vol.Required(
                        CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                    ): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return AndroidTVBridgeOptionsFlow(config_entry)


class AndroidTVBridgeOptionsFlow(config_entries.OptionsFlow):
    """Handle Android TV Bridge options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **self._config_entry.options,
                    CONF_EXPOSED_ACTIONS: list(user_input.get(CONF_EXPOSED_ACTIONS) or []),
                },
            )
        current = self._config_entry.options.get(CONF_EXPOSED_ACTIONS) or []
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EXPOSED_ACTIONS, default=list(current)
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=list(EXPOSED_ACTION_DOMAINS), multiple=True
                        )
                    ),
                }
            ),
        )
