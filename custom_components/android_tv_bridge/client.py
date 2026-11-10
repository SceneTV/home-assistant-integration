"""Local HTTP and WebSocket client for SceneTV launchers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from aiohttp import (
    ClientError,
    ClientResponse,
    ClientSession,
    ClientWebSocketResponse,
    WSServerHandshakeError,
)

from .const import DEFAULT_API_VERSION, DEFAULT_TIMEOUT


class AndroidTVBridgeError(Exception):
    """Base error for Android TV Bridge client failures."""


class AndroidTVBridgeAuthError(AndroidTVBridgeError):
    """Raised when the launcher rejects authentication."""


class AndroidTVBridgeConnectionError(AndroidTVBridgeError):
    """Raised when the launcher cannot be reached."""


class AndroidTVBridgeResponseError(AndroidTVBridgeError):
    """Raised when the launcher returns an invalid or failed response."""


class AndroidTVBridgeClient:
    """Client for the local launcher bridge API."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        *,
        token: str | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.host = host
        self.port = port
        self.token = token
        self.api_version = api_version

    @property
    def base_url(self) -> str:
        """Return the HTTP API base URL."""
        return f"http://{self.host}:{self.port}/api/{self.api_version}"

    @property
    def websocket_url(self) -> str:
        """Return the WebSocket API URL."""
        return f"ws://{self.host}:{self.port}/api/{self.api_version}/ws"

    def _headers(self, *, authenticated: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _json_or_error(self, response: ClientResponse) -> dict[str, Any]:
        if response.status in (401, 403):
            raise AndroidTVBridgeAuthError("Authentication was rejected by the launcher")
        if response.status >= 400:
            body = await response.text()
            raise AndroidTVBridgeResponseError(
                f"Launcher returned HTTP {response.status}: {body[:200]}"
            )
        try:
            data = await response.json(content_type=None)
        except ValueError as err:
            raise AndroidTVBridgeResponseError("Launcher returned invalid JSON") from err
        if not isinstance(data, dict):
            raise AndroidTVBridgeResponseError("Launcher returned a non-object response")
        return data

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        authenticated: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with asyncio.timeout(timeout):
                async with self._session.request(
                    method,
                    url,
                    json=json,
                    headers=self._headers(authenticated=authenticated),
                ) as response:
                    return await self._json_or_error(response)
        except TimeoutError as err:
            raise AndroidTVBridgeConnectionError(f"Timed out contacting {url}") from err
        except ClientError as err:
            raise AndroidTVBridgeConnectionError(f"Could not contact {url}") from err

    async def async_get_metadata(self) -> dict[str, Any]:
        """Fetch unauthenticated launcher metadata."""
        return await self._request_json("GET", "/metadata", authenticated=False)

    async def async_get_health(self) -> dict[str, Any]:
        """Fetch authenticated launcher health."""
        return await self._request_json("GET", "/health")

    async def async_get_state(self) -> dict[str, Any]:
        """Fetch an authenticated state snapshot."""
        return await self._request_json("GET", "/state")

    async def async_link_pairing(
        self,
        *,
        ha_instance_id: str,
        ha_name: str,
        nonce: str,
    ) -> dict[str, Any]:
        """Trade a nonce delivered through Remote v2 for a bridge token.

        Raises AndroidTVBridgeAuthError until the launcher has received the link.
        """
        return await self._request_json(
            "POST",
            "/pairing/link",
            json={
                "client_type": "home_assistant",
                "client_id": ha_instance_id,
                "client_name": ha_name,
                "nonce": nonce,
            },
            authenticated=False,
        )

    async def async_revoke_pairing(self) -> dict[str, Any]:
        """Revoke this Home Assistant pairing."""
        return await self._request_json("POST", "/pairing/revoke")

    async def async_open_websocket(self) -> ClientWebSocketResponse:
        """Open an authenticated WebSocket connection."""
        try:
            return await self._session.ws_connect(
                self.websocket_url,
                headers=self._headers(),
                heartbeat=30,
            )
        except WSServerHandshakeError as err:
            if err.status in (401, 403):
                raise AndroidTVBridgeAuthError(
                    "Authentication was rejected by the launcher"
                ) from err
            raise AndroidTVBridgeConnectionError(
                f"Could not open WebSocket to {self.websocket_url}: HTTP {err.status}"
            ) from err
        except ClientError as err:
            raise AndroidTVBridgeConnectionError(
                f"Could not open WebSocket to {self.websocket_url}"
            ) from err
