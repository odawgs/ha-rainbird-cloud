"""Rain sensor for Rain Bird Cloud."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RainbirdCloudConfigEntry, RainbirdCloudCoordinator
from .entity import RainbirdCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RainbirdCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the rain sensor when the controller reports one."""
    if entry.runtime_data.has_rain_sensor:
        async_add_entities([RainSensor(entry.runtime_data.coordinator)])


class RainSensor(RainbirdCloudEntity, BinarySensorEntity):
    """The controller's wired rain sensor (unknown until the stream reports it)."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_translation_key = "rain_sensor"

    def __init__(self, coordinator: RainbirdCloudCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "rain-sensor")

    @property
    def is_on(self) -> bool | None:
        """Return True when the rain sensor is wet."""
        return self.coordinator.data.rain_sensor
