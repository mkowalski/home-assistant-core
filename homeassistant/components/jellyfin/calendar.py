"""Support for Jellyfin Live TV recordings as a calendar."""

from datetime import datetime
from typing import override

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEvent,
    CalendarEventStatus,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import RECORDING_STATUS_CONFLICTED_NOT_OK
from .coordinator import (
    JellyfinConfigEntry,
    JellyfinLiveTvCoordinator,
    JellyfinRecording,
)
from .entity import JellyfinServerEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyfinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Jellyfin recordings calendar from a config entry."""
    if (coordinator := entry.runtime_data.live_tv) is None:
        return

    async_add_entities([JellyfinRecordingsCalendarEntity(coordinator)])


class JellyfinRecordingsCalendarEntity(JellyfinServerEntity, CalendarEntity):
    """Calendar of scheduled and in-progress Live TV recordings."""

    coordinator: JellyfinLiveTvCoordinator
    _attr_translation_key = "recordings"

    def __init__(self, coordinator: JellyfinLiveTvCoordinator) -> None:
        """Initialize the Jellyfin recordings calendar."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.server_id}-recordings"

    @property
    @override
    def event(self) -> CalendarEvent | None:
        """Return the in-progress recording, or else the next scheduled one."""
        now = dt_util.utcnow()
        return next(
            (
                _calendar_event(recording)
                for recording in self.coordinator.data
                if recording.end > now
            ),
            None,
        )

    @override
    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the recordings that overlap the requested time range."""
        return [
            _calendar_event(recording)
            for recording in self.coordinator.data
            if recording.end > start_date and recording.start < end_date
        ]


def _calendar_event(recording: JellyfinRecording) -> CalendarEvent:
    """Convert a recording into a calendar event."""
    summary = recording.name
    if recording.episode_title:
        summary = f"{summary} - {recording.episode_title}"

    description_lines = [
        line for line in (recording.channel_name, recording.overview) if line
    ]

    return CalendarEvent(
        start=recording.start,
        end=recording.end,
        summary=summary,
        description="\n\n".join(description_lines) or None,
        uid=recording.timer_id,
        status=(
            CalendarEventStatus.TENTATIVE
            if recording.status == RECORDING_STATUS_CONFLICTED_NOT_OK
            else CalendarEventStatus.CONFIRMED
        ),
    )
