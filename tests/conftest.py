"""Fixtures for Rain Bird Cloud tests."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.rainbird_cloud.api import CloudState, Program, Station

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


@pytest.fixture
def mock_api():
    """Patch the cloud API with Owen's controller layout."""
    with (
        patch(
            "custom_components.rainbird_cloud.RainbirdCloudApi", autospec=True
        ) as init_cls,
        patch(
            "custom_components.rainbird_cloud.config_flow.RainbirdCloudApi",
            new=init_cls,
        ),
        patch(
            "custom_components.rainbird_cloud.coordinator.AsyncRainbirdCloudStream"
        ) as stream_cls,
    ):
        api = init_cls.return_value
        api.satellite_id = 721646
        api.device_uuid = "uuid-1"
        api.token = "tok"
        api.satellites = AsyncMock(return_value=[(721646, "ARC 7FA0", 6)])
        api.satellite = AsyncMock(
            return_value={"versionString": "4.103.0", "rainDelayDaysRemaining": 0}
        )
        api.stations = {
            z: Station(17816621 + z, z, f"Station {z}") for z in range(1, 7)
        }
        api.load_stations = AsyncMock(return_value=api.stations)
        api.programs = AsyncMock(return_value=[Program(3576743, "Program A")])
        api.has_rain_sensor = AsyncMock(return_value=True)
        api.state = AsyncMock(return_value=CloudState())

        async def _listen():
            if False:
                yield None

        stream_cls.return_value.listen = _listen
        yield api
