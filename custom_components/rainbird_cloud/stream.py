"""Rain Bird's AppSync live stream, with the handshake AppSync accepts.

pyrainbird 6.6.0's AsyncRainbirdCloudStream is refused with "The request
headers are invalid": it sends the handshake header as URL-safe base64 with the
padding stripped, and its subscription start message serializes the auth key
as "authorization" instead of "Authorization". This subclass keeps pyrainbird's
event parsing and replaces the connection itself.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse
from collections.abc import AsyncIterator

import aiohttp
from pyrainbird.cloud.models import SUBSCRIBE_DEVICE_STATE_QUERY, CloudStreamEvent
from pyrainbird.cloud.stream import API_HOST, WS_ENDPOINT, AsyncRainbirdCloudStream
from pyrainbird.exceptions import RainbirdAuthException

_LOGGER = logging.getLogger(__name__)

SUBSCRIPTION_ID = "device_state"
RECEIVE_TIMEOUT = 360


def _encode(obj: dict) -> str:
    """Return standard, padded base64 JSON, quoted for a URL."""
    raw = base64.b64encode(json.dumps(obj).encode()).decode()
    return urllib.parse.quote(raw, safe="")


class StreamClosed(Exception):
    """The server ended the stream; reconnect."""


class RainbirdStream(AsyncRainbirdCloudStream):
    """One connection to the live stream; the caller handles reconnects."""

    def _get_connection_url(self, token: str) -> str:
        header = {"host": API_HOST, "Authorization": token}
        return f"{WS_ENDPOINT}?header={_encode(header)}&payload={_encode({})}"

    async def listen(self) -> AsyncIterator[CloudStreamEvent]:
        """Connect, subscribe and yield events until the connection ends."""
        token = await self._token_provider.async_get_token(
            force_refresh=self._force_refresh_token
        )
        self._force_refresh_token = False
        async with self._session.ws_connect(
            self._get_connection_url(token), protocols=["graphql-ws"]
        ) as ws:
            await ws.send_json({"type": "connection_init"})
            while True:
                # AppSync sends a keep-alive at least every 5 minutes.
                msg = await ws.receive(timeout=RECEIVE_TIMEOUT)
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                data = msg.json()
                kind = data.get("type")
                if kind == "connection_ack":
                    await ws.send_json(self._start_message(token))
                elif kind == "start_ack":
                    _LOGGER.info("Rain Bird live stream subscribed")
                elif kind == "data":
                    if event := self._parse_event(data):
                        yield event
                elif kind in ("connection_error", "error"):
                    errors = (data.get("payload") or {}).get("errors") or []
                    text = "; ".join(
                        str(e.get("message") or e.get("errorType")) for e in errors
                    )
                    if any(
                        "unauthorized" in str(e.get("message", "")).lower()
                        or e.get("errorType") == "UnauthorizedException"
                        for e in errors
                    ):
                        self._force_refresh_token = True
                    raise RainbirdAuthException(f"AppSync refused: {text or kind}")
                elif kind == "complete":
                    break
        raise StreamClosed("connection closed")

    def _start_message(self, token: str) -> dict:
        return {
            "id": SUBSCRIPTION_ID,
            "type": "start",
            "payload": {
                "data": json.dumps(
                    {
                        "query": SUBSCRIBE_DEVICE_STATE_QUERY,
                        "variables": {"PK": self._device_uuid},
                    }
                ),
                "extensions": {
                    "authorization": {"host": API_HOST, "Authorization": token}
                },
            },
        }
