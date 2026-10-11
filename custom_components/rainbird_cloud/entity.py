"""Base entity for Rain Bird Cloud."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import RainbirdCloudCoordinator


class RainbirdCloudEntity(CoordinatorEntity[RainbirdCloudCoordinator]):
    """An entity on the Rain Bird controller device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RainbirdCloudCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_id}-{key}"
        self._attr_device_info = coordinator.device_info
