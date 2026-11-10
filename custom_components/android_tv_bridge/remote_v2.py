"""Android TV Remote v2 pairing, used to prove that the user sits at the TV.

The launcher shows no approval prompt. Home Assistant pairs with the TV's Android TV Remote
service (the user types the code the TV shows), then asks that service to open a
``scenetv://pair`` link. The launcher accepts the link only from the Remote service and hands
Home Assistant a bridge token in exchange for the nonce in it.
"""

from __future__ import annotations

from urllib.parse import quote

from androidtvremote2 import (
    AndroidTVRemote,
    CannotConnect,
    ConnectionClosed,
    InvalidAuth,
)

from homeassistant.core import HomeAssistant

from .client import AndroidTVBridgeError

CLIENT_NAME = "Home Assistant"
CERT_FILE = "scenetv_remote_cert.pem"
KEY_FILE = "scenetv_remote_key.pem"


class RemoteV2Error(AndroidTVBridgeError):
    """The TV's Android TV Remote service could not be reached or paired."""


class RemoteV2InvalidCode(RemoteV2Error):
    """The pairing code did not match the one on the TV."""


def pair_link(nonce: str, client_id: str) -> str:
    """The link the launcher's ``PairLinkActivity`` receives."""
    return f"scenetv://pair?n={quote(nonce, safe='')}&c={quote(client_id, safe='')}"


class RemoteV2Pairing:
    """One pairing attempt with a TV's Android TV Remote service."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        """Prepare a pairing with the TV at [host]."""
        self._remote = AndroidTVRemote(
            CLIENT_NAME,
            hass.config.path(".storage", CERT_FILE),
            hass.config.path(".storage", KEY_FILE),
            host,
        )

    async def async_start(self) -> bool:
        """Connect, or start pairing. Returns True when the user must enter a code."""
        try:
            await self._remote.async_generate_cert_if_missing()
            try:
                # Succeeds without a code when this Home Assistant is already paired.
                await self._remote.async_connect()
            except InvalidAuth:
                pass
            else:
                return False
            await self._remote.async_start_pairing()
        except (CannotConnect, ConnectionClosed, OSError) as err:
            raise RemoteV2Error("Could not reach the TV's remote service") from err
        return True

    async def async_finish(self, code: str) -> None:
        """Complete pairing with the code the TV shows, then connect."""
        try:
            await self._remote.async_finish_pairing(code)
            await self._remote.async_connect()
        except InvalidAuth as err:
            # A wrong code ends this attempt on the TV; show a fresh code.
            await self._restart()
            raise RemoteV2InvalidCode("Wrong pairing code") from err
        except (CannotConnect, ConnectionClosed, OSError) as err:
            raise RemoteV2Error("Pairing with the TV's remote service failed") from err

    async def _restart(self) -> None:
        try:
            await self._remote.async_start_pairing()
        except (CannotConnect, ConnectionClosed, OSError) as err:
            raise RemoteV2Error("Could not restart pairing") from err

    async def async_send_link(self, link: str) -> None:
        """Ask the TV's Remote service to open [link]."""
        try:
            self._remote.send_launch_app_command(link)
        except ConnectionClosed as err:
            raise RemoteV2Error("The TV's remote service closed the connection") from err

    def close(self) -> None:
        """Release the connection."""
        self._remote.disconnect()
