"""Support for Jellyfin binary sensors."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import RECORDING_STATUS_IN_PROGRESS
from .coordinator import JellyfinConfigEntry, JellyfinLiveTvCoordinator
from .entity import JellyfinServerEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyfinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Jellyfin binary sensors based on a config entry."""
    if (coordinator := entry.runtime_data.live_tv) is None:
        return

    async_add_entities([JellyfinRecordingBinarySensor(coordinator)])


class JellyfinRecordingBinarySensor(JellyfinServerEntity, BinarySensorEntity):
    """Binary sensor that is on while the Jellyfin DVR is recording."""

    coordinator: JellyfinLiveTvCoordinator
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "recording"

    def __init__(self, coordinator: JellyfinLiveTvCoordinator) -> None:
        """Initialize the Jellyfin recording binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.server_id}-recording"

    @property
    @override
    def is_on(self) -> bool:
        """Return True if a recording is in progress."""
        return any(
            recording.status == RECORDING_STATUS_IN_PROGRESS
            for recording in self.coordinator.data
        )
