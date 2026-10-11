"""Zone switches for Rain Bird Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyrainbird.exceptions import RainbirdApiException, RainbirdConnectionError

from .api import Station
from .const import CONF_DURATION, DEFAULT_DURATION_MINUTES
from .coordinator import RainbirdCloudConfigEntry, RainbirdCloudCoordinator
from .entity import RainbirdCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RainbirdCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one switch per zone."""
    data = entry.runtime_data
    async_add_entities(
        RainbirdCloudZone(data.coordinator, station)
        for station in sorted(data.api.stations.values(), key=lambda s: s.zone)
    )


class RainbirdCloudZone(RainbirdCloudEntity, SwitchEntity):
    """A zone. On runs it for the default watering time; off stops watering."""

    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator: RainbirdCloudCoordinator, station: Station) -> None:
        """Initialize the zone."""
        super().__init__(coordinator, f"zone-{station.zone}")
        self._zone = station.zone
        self._attr_name = station.name

    @property
    def is_on(self) -> bool:
        """Return True while the zone is watering."""
        return self._zone in self.coordinator.data.active_zones

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the zone number and raw status."""
        return {
            "zone": self._zone,
            "remaining_seconds": self.coordinator.data.remaining.get(self._zone),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Run the zone."""
        minutes = int(
            kwargs.get(
                "duration",
                self.coordinator.config_entry.options.get(
                    CONF_DURATION, DEFAULT_DURATION_MINUTES
                ),
            )
        )
        try:
            await self.coordinator.api.start_zone(self._zone, minutes)
        except (RainbirdApiException, RainbirdConnectionError) as err:
            raise HomeAssistantError(f"Rain Bird cloud error: {err}") from err
        self.coordinator.zone_started(self._zone, minutes * 60)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop watering (the controller stops every zone)."""
        try:
            await self.coordinator.api.stop_all()
        except (RainbirdApiException, RainbirdConnectionError) as err:
            raise HomeAssistantError(f"Rain Bird cloud error: {err}") from err
        self.coordinator.all_stopped()
