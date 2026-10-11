"""Sensors for Rain Bird Cloud."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RainbirdCloudConfigEntry, RainbirdCloudCoordinator
from .entity import RainbirdCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RainbirdCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([ActiveZoneSensor(coordinator), RemainingSensor(coordinator)])


class ActiveZoneSensor(RainbirdCloudEntity, SensorEntity):
    """Which zone is watering now, or none."""

    _attr_translation_key = "active_zone"
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator: RainbirdCloudCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "active-zone")

    @property
    def native_value(self) -> str:
        """Return the watering zone's name, or 'None'."""
        stations = self.coordinator.api.stations
        active = sorted(self.coordinator.data.active_zones)
        if not active:
            return "None"
        return ", ".join(
            stations[z].name if z in stations else f"Zone {z}" for z in active
        )


class RemainingSensor(RainbirdCloudEntity, SensorEntity):
    """Seconds left on the zone that is watering."""

    _attr_translation_key = "remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: RainbirdCloudCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "remaining")

    @property
    def native_value(self) -> int:
        """Return the longest remaining run time, or 0."""
        return max(self.coordinator.data.remaining.values(), default=0)
