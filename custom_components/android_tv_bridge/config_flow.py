"""Config flow for Android TV Bridge."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import AndroidTVBridgeClient, AndroidTVBridgeError
from .const import (
    CONF_API_VERSION,
    CONF_TOKEN,
    DEFAULT_API_VERSION,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

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
        self._pairing_request_id: str | None = None

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
        """Poll a pending TV approval prompt."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                status = await self._async_pairing_status()
            except AndroidTVBridgeError:
                errors["base"] = "cannot_connect"
            else:
                state = str(status.get("status") or "").lower()
                if state == "approved" and status.get("token"):
                    return await self._async_create_entry(str(status["token"]))
                if state in {"rejected", "expired", "revoked"}:
                    return self.async_abort(reason=f"pairing_{state}")
                errors["base"] = "pairing_pending"

        return self.async_show_form(step_id="pair", errors=errors)

    async def _async_fetch_metadata(self) -> None:
        assert self._host is not None
        client = AndroidTVBridgeClient(
            async_get_clientsession(self.hass),
            self._host,
            self._port,
            api_version=self._api_version,
        )
        self._metadata = await client.async_get_metadata()
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
        assert self._host is not None
        client = AndroidTVBridgeClient(
            async_get_clientsession(self.hass),
            self._host,
            self._port,
            api_version=self._api_version,
        )
        ha_instance_id = await instance_id.async_get(self.hass)
        response = await client.async_request_pairing(
            ha_instance_id=ha_instance_id,
            ha_name=self.hass.config.location_name,
        )
        if response.get("status") == "approved" and response.get("token"):
            return await self._async_create_entry(str(response["token"]))
        self._pairing_request_id = str(
            response.get("request_id") or response.get("pairing_request_id") or ""
        )
        if not self._pairing_request_id:
            raise AndroidTVBridgeError("Pairing response did not include a request id")
        return self.async_show_form(step_id="pair")

    async def _async_pairing_status(self) -> dict[str, Any]:
        assert self._host is not None
        assert self._pairing_request_id is not None
        client = AndroidTVBridgeClient(
            async_get_clientsession(self.hass),
            self._host,
            self._port,
            api_version=self._api_version,
        )
        return await client.async_get_pairing_status(self._pairing_request_id)

    async def _async_create_entry(self, token: str) -> config_entries.ConfigFlowResult:
        assert self._host is not None
        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_NAME: self._name,
            CONF_TOKEN: token,
            CONF_API_VERSION: self._api_version,
        }
        return self.async_create_entry(title=self._name, data=data)

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
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
