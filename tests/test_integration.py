"""Config flow, setup and control tests for Rain Bird Cloud."""

import datetime

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pyrainbird.cloud.models import (
    ConnectedData,
    ConnectionStatusEvent,
    RainSensorStateData,
    RainSensorStateEvent,
    StationStateData,
    StationStateEvent,
)
from pyrainbird.exceptions import RainbirdAuthException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rainbird_cloud.const import (
    CONF_DURATION,
    CONF_SATELLITE_ID,
    DOMAIN,
)

NOW = datetime.datetime.now(datetime.UTC)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="721646",
        title="ARC 7FA0",
        data={
            CONF_USERNAME: "a@b.c",
            CONF_PASSWORD: "pw",
            CONF_SATELLITE_ID: 721646,
        },
        options={CONF_DURATION: 6},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow_single_controller(hass: HomeAssistant, mock_api) -> None:
    """One controller on the account creates the entry directly."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: " a@b.c ", CONF_PASSWORD: "pw"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ARC 7FA0"
    assert result["data"][CONF_SATELLITE_ID] == 721646
    assert result["data"][CONF_USERNAME] == "a@b.c"
    assert result["options"] == {CONF_DURATION: 6}


async def test_config_flow_bad_password(hass: HomeAssistant, mock_api) -> None:
    """A rejected login shows invalid_auth."""
    mock_api.satellites.side_effect = RainbirdAuthException("no")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "a@b.c", CONF_PASSWORD: "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_setup_entities(hass: HomeAssistant, mock_api) -> None:
    """Setup creates six zones, buttons, rain delay, sensors and rain sensor."""
    await _setup(hass)
    for zone in range(1, 7):
        assert hass.states.get(f"switch.arc_7fa0_station_{zone}").state == "off"
    assert hass.states.get("button.arc_7fa0_stop_watering")
    assert hass.states.get("button.arc_7fa0_run_program_a")
    assert hass.states.get("number.arc_7fa0_rain_delay").state == "0"
    assert hass.states.get("sensor.arc_7fa0_watering_now").state == "None"
    assert hass.states.get("binary_sensor.arc_7fa0_rain_sensor").state == "unknown"


async def test_turn_on_and_off(hass: HomeAssistant, mock_api) -> None:
    """Turning a zone on starts it for the default time and shows it on."""
    await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.arc_7fa0_station_1"}, blocking=True
    )
    mock_api.start_zone.assert_awaited_once_with(1, 6)
    assert hass.states.get("switch.arc_7fa0_station_1").state == "on"
    assert hass.states.get("sensor.arc_7fa0_watering_now").state == "Station 1"
    assert 350 <= int(hass.states.get("sensor.arc_7fa0_time_remaining").state) <= 360

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.arc_7fa0_station_1"}, blocking=True
    )
    mock_api.stop_all.assert_awaited_once()
    assert hass.states.get("switch.arc_7fa0_station_1").state == "off"


async def test_unload(hass: HomeAssistant, mock_api) -> None:
    """Unloading with a zone running leaves no timers behind."""
    entry = await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.arc_7fa0_station_2"}, blocking=True
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_stream_events(hass: HomeAssistant, mock_api) -> None:
    """Live stream events turn zones and the rain sensor on and off."""
    entry = await _setup(hass)
    coordinator = entry.runtime_data.coordinator

    coordinator._handle_event(
        StationStateEvent(721646, "uuid-1", NOW, 3, StationStateData(1, 120))
    )
    await hass.async_block_till_done()
    assert hass.states.get("switch.arc_7fa0_station_3").state == "on"

    coordinator._handle_event(
        StationStateEvent(721646, "uuid-1", NOW, 3, StationStateData(0, 0))
    )
    await hass.async_block_till_done()
    assert hass.states.get("switch.arc_7fa0_station_3").state == "off"

    coordinator._handle_event(
        ConnectionStatusEvent(
            721646,
            "uuid-1",
            NOW,
            ConnectedData(state=1, active_station=5, remain_sec=60),
        )
    )
    await hass.async_block_till_done()
    assert hass.states.get("switch.arc_7fa0_station_5").state == "on"

    coordinator._handle_event(
        RainSensorStateEvent(721646, "uuid-1", NOW, RainSensorStateData(1))
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.arc_7fa0_rain_sensor").state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_rain_delay(hass: HomeAssistant, mock_api) -> None:
    """Setting the number sets the rain delay."""
    await _setup(hass)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.arc_7fa0_rain_delay", "value": 2},
        blocking=True,
    )
    mock_api.set_rain_delay.assert_awaited_once_with(2)
