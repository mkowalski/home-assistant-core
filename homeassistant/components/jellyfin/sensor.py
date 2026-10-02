"""Support for Jellyfin sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import RECORDING_STATUS_NEW
from .coordinator import JellyfinConfigEntry, JellyfinCoordinator, JellyfinRecording
from .entity import JellyfinServerEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class JellyfinSensorEntityDescription[_DataT](SensorEntityDescription):
    """Describes Jellyfin sensor entity."""

    value_fn: Callable[[_DataT], StateType | datetime]


def _count_now_playing(data: dict[str, dict[str, Any]]) -> int:
    """Count the number of now playing."""
    session_ids = [
        sid for (sid, session) in data.items() if "NowPlayingItem" in session
    ]

    return len(session_ids)


def _next_recording_start(recordings: list[JellyfinRecording]) -> datetime | None:
    """Return when the next scheduled recording starts, padding included."""
    return next(
        (
            recording.start
            for recording in recordings
            if recording.status == RECORDING_STATUS_NEW
        ),
        None,
    )


SESSION_SENSOR_TYPES: tuple[
    JellyfinSensorEntityDescription[dict[str, dict[str, Any]]], ...
] = (
    JellyfinSensorEntityDescription(
        key="watching",
        translation_key="watching",
        value_fn=_count_now_playing,
    ),
)

LIVE_TV_SENSOR_TYPES: tuple[
    JellyfinSensorEntityDescription[list[JellyfinRecording]], ...
] = (
    JellyfinSensorEntityDescription(
        key="next_recording",
        translation_key="next_recording",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_recording_start,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyfinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Jellyfin sensor based on a config entry."""
    entities: list[SensorEntity] = [
        JellyfinServerSensor(entry.runtime_data.sessions, description)
        for description in SESSION_SENSOR_TYPES
    ]
    if (live_tv_coordinator := entry.runtime_data.live_tv) is not None:
        entities.extend(
            JellyfinServerSensor(live_tv_coordinator, description)
            for description in LIVE_TV_SENSOR_TYPES
        )

    async_add_entities(entities)


class JellyfinServerSensor[_DataT](JellyfinServerEntity, SensorEntity):
    """Defines a Jellyfin sensor entity."""

    coordinator: JellyfinCoordinator[_DataT]
    entity_description: JellyfinSensorEntityDescription[_DataT]

    def __init__(
        self,
        coordinator: JellyfinCoordinator[_DataT],
        description: JellyfinSensorEntityDescription[_DataT],
    ) -> None:
        """Initialize Jellyfin sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.server_id}-{description.key}"

    @property
    @override
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
