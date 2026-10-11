"""Buttons for Rain Bird Cloud: stop all, and one per program."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyrainbird.exceptions import RainbirdApiException, RainbirdConnectionError

from .api import Program
from .coordinator import RainbirdCloudConfigEntry, RainbirdCloudCoordinator
from .entity import RainbirdCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RainbirdCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    data = entry.runtime_data
    entities: list[ButtonEntity] = [StopAllButton(data.coordinator)]
    entities.extend(RunProgramButton(data.coordinator, p) for p in data.programs)
    async_add_entities(entities)


class StopAllButton(RainbirdCloudEntity, ButtonEntity):
    """Stop all watering."""

    _attr_translation_key = "stop_all"
    _attr_icon = "mdi:water-off"

    def __init__(self, coordinator: RainbirdCloudCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "stop-all")

    async def async_press(self) -> None:
        """Stop all zones."""
        try:
            await self.coordinator.api.stop_all()
        except (RainbirdApiException, RainbirdConnectionError) as err:
            raise HomeAssistantError(f"Rain Bird cloud error: {err}") from err
        self.coordinator.all_stopped()


class RunProgramButton(RainbirdCloudEntity, ButtonEntity):
    """Start one of the controller's programs."""

    _attr_translation_key = "run_program"
    _attr_icon = "mdi:play"

    def __init__(self, coordinator: RainbirdCloudCoordinator, program: Program) -> None:
        """Initialize the button."""
        super().__init__(coordinator, f"program-{program.program_id}")
        self._program_id = program.program_id
        self._attr_translation_placeholders = {"program": program.name}

    async def async_press(self) -> None:
        """Start the program."""
        try:
            await self.coordinator.api.start_program(self._program_id)
        except (RainbirdApiException, RainbirdConnectionError) as err:
            raise HomeAssistantError(f"Rain Bird cloud error: {err}") from err
        await self.coordinator.async_request_refresh()
