"""Parsing tests for the cloud API wrapper, using replies seen from an ARC6."""

from unittest.mock import AsyncMock

from custom_components.rainbird_cloud.api import RainbirdCloudApi, Station

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
