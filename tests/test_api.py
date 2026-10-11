"""Parsing tests for the cloud API wrapper, using replies seen from an ARC6."""

import base64
import json
import urllib.parse
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from pyrainbird.cloud.stream import API_HOST

from custom_components.rainbird_cloud.api import RainbirdCloudApi, Station
from custom_components.rainbird_cloud.stream import RainbirdStream, StreamClosed

RUN_STATUS = [
    {
        "programId": 3576743,
        "satelliteId": 721646,
        "runStationStatuses": [
            {"stationId": 17816622, "stationTerminal": 1, "status": "-"},
            {"stationId": 17816623, "stationTerminal": 2, "status": "Running"},
        ],
    },
    {"programId": 3576744, "satelliteId": 721646, "runStationStatuses": []},
]


async def test_state_parsing() -> None:
    """Nested run statuses, '-' as idle, and days remaining are read."""
    api = RainbirdCloudApi(AsyncMock(), "a", "b", satellite_id=721646)
    api.stations = {
        1: Station(17816622, 1, "Station 1"),
        2: Station(17816623, 2, "Station 2"),
    }
    api._client = AsyncMock()
    api._client.get_run_station_status.return_value = RUN_STATUS
    api._client.get_satellite.return_value = {
        "rainDelayDaysRemaining": 2,
        "rainDelayLong": 0,
    }
    state = await api.state()
    assert state.active_zones == {2}
    assert state.rain_delay_days == 2


async def test_rain_sensor_detection() -> None:
    """The ARC6's 'Local Sensor' with a rain sensor model counts as a rain sensor."""
    api = RainbirdCloudApi(AsyncMock(), "a", "b", satellite_id=721646)
    api._client = AsyncMock()
    api._client.get_sensor_list.return_value = [
        {
            "id": 1321666,
            "name": "Local Sensor",
            "type": -1,
            "model": "Rain Sensor Prevent (Alarm)",
            "onOffState": 0,
        }
    ]
    assert await api.has_rain_sensor()
    assert await api.rain_sensor_state() is False
    api._client.get_sensor_list.return_value[0]["onOffState"] = 1
    assert await api.rain_sensor_state() is True


def test_stream_handshake() -> None:
    """The handshake uses padded standard base64 and 'Authorization' keys."""
    stream = RainbirdStream(AsyncMock(), 721646, "uuid-1", AsyncMock())
    url = stream._get_connection_url("tok+/=")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    header = json.loads(base64.b64decode(query["header"][0], validate=True))
    assert header == {"host": API_HOST, "Authorization": "tok+/="}
    assert query["payload"] == ["e30="]
    auth = stream._start_message("tok")["payload"]["extensions"]["authorization"]
    assert auth == {"host": API_HOST, "Authorization": "tok"}


async def test_stream_listen() -> None:
    """The stream subscribes after the ack and yields station events."""
    data = {
        "type": "data",
        "payload": {
            "data": {
                "onUpdateDeviceStateTable": {
                    "PK": "uuid-1",
                    "SK": "Station1",
                    "Data": json.dumps({"state": 1, "remainSec": 300}),
                    "TimeStamp": 1791712800,
                }
            }
        },
    }
    incoming = [{"type": "connection_ack"}, {"type": "start_ack"}, {"type": "ka"}, data]
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.receive = AsyncMock(
        side_effect=[
            *(
                MagicMock(type=aiohttp.WSMsgType.TEXT, json=lambda m=m: m)
                for m in incoming
            ),
            MagicMock(type=aiohttp.WSMsgType.CLOSED),
        ]
    )
    session = MagicMock()
    session.ws_connect.return_value.__aenter__.return_value = ws
    provider = AsyncMock()
    provider.async_get_token.return_value = "tok"
    stream = RainbirdStream(provider, 721646, "uuid-1", session)

    events = []
    with pytest.raises(StreamClosed):
        async for event in stream.listen():
            events.append(event)

    assert [m.args[0]["type"] for m in ws.send_json.call_args_list] == [
        "connection_init",
        "start",
    ]
    assert len(events) == 1
    assert events[0].zone == 1
    assert events[0].is_watering
