"""Rain delay number for Rain Bird Cloud."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyrainbird.exceptions import RainbirdApiException, RainbirdConnectionError

from .coordinator import RainbirdCloudConfigEntry, RainbirdCloudCoordinator
from .entity import RainbirdCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RainbirdCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the rain delay."""
    async_add_entities([RainDelayNumber(entry.runtime_data.coordinator)])


class RainDelayNumber(RainbirdCloudEntity, NumberEntity):
    """Days of rain delay; 0 clears it."""

    _attr_native_min_value = 0
    _attr_native_max_value = 14
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_translation_key = "rain_delay"
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: RainbirdCloudCoordinator) -> None:
        """Initialize the number."""
        super().__init__(coordinator, "rain-delay")

    @property
    def native_value(self) -> float | None:
        """Return the remaining rain delay in days."""
        return self.coordinator.data.rain_delay_days

    async def async_set_native_value(self, value: float) -> None:
        """Set the rain delay."""
        try:
            await self.coordinator.api.set_rain_delay(int(value))
        except (RainbirdApiException, RainbirdConnectionError) as err:
            raise HomeAssistantError(f"Rain Bird cloud error: {err}") from err
        await self.coordinator.async_request_refresh()
