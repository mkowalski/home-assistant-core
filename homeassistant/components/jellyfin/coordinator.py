"""Data update coordinator for the Jellyfin integration."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, override

from jellyfin_apiclient_python import JellyfinClient
from jellyfin_apiclient_python.exceptions import HTTPException

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client_wrapper import CannotConnect, is_live_tv_enabled
from .const import (
    ACTIVE_RECORDING_STATUSES,
    CONF_CLIENT_DEVICE_ID,
    DOMAIN,
    LOGGER,
    USER_APP_NAME,
)

type JellyfinConfigEntry = ConfigEntry[JellyfinDataUpdateCoordinator]


@dataclass(frozen=True, kw_only=True, slots=True)
class JellyfinRecording:
    """A scheduled or in-progress Live TV recording."""

    timer_id: str
    name: str
    episode_title: str | None
    channel_name: str | None
    overview: str | None
    status: str
    # Includes the pre- and post-padding, so this is when the tuner is busy
    start: datetime
    end: datetime


class JellyfinDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Data update coordinator for Jellyfin sessions and recordings."""

    config_entry: JellyfinConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: JellyfinConfigEntry,
        api_client: JellyfinClient,
        system_info: dict[str, Any],
        user_id: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=10),
        )
        self.api_client = api_client
        self.server_id: str = system_info["Id"]
        self.server_name: str = system_info["Name"]
        self.server_version: str | None = system_info.get("Version")
        self.client_device_id: str = config_entry.data[CONF_CLIENT_DEVICE_ID]
        self.user_id: str = user_id

        self.session_ids: set[str] = set()
        self.remote_session_ids: set[str] = set()
        self.device_ids: set[str] = set()
        self.live_tv_enabled = False
        self.recordings: list[JellyfinRecording] = []

    @override
    async def _async_setup(self) -> None:
        """Determine whether the signed-in user can access Live TV."""
        try:
            self.live_tv_enabled = await self.hass.async_add_executor_job(
                is_live_tv_enabled, self.api_client
            )
        except CannotConnect as ex:
            raise UpdateFailed("Cannot read Live TV info from Jellyfin") from ex

    @override
    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Get the latest sessions and recording timers from Jellyfin."""
        timers: dict[str, Any] | None = None
        try:
            sessions = await self.hass.async_add_executor_job(
                self.api_client.jellyfin.sessions
            )
            if self.live_tv_enabled:
                timers = await self.hass.async_add_executor_job(
                    self.api_client.jellyfin.get_live_tv_timers
                )
        except HTTPException as ex:
            if ex.status == "Unauthorized":
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN, translation_key="unauthorized"
                ) from ex
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="update_failed"
            ) from ex

        # The client library swallows HTTP 500 responses and returns None
        if sessions is None or (self.live_tv_enabled and timers is None):
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="update_failed"
            )

        sessions_by_id: dict[str, dict[str, Any]] = {
            session["Id"]: session
            for session in sessions
            if session["DeviceId"] != self.client_device_id
            and session["Client"] != USER_APP_NAME
        }

        recordings = []
        if timers is not None:
            recordings = [
                recording
                for timer in timers["Items"]
                if (recording := _parse_recording(timer)) is not None
            ]
        recordings.sort(key=lambda recording: recording.start)
        self.recordings = recordings
        self.device_ids = {session["DeviceId"] for session in sessions_by_id.values()}

        return sessions_by_id


def _parse_recording(timer: dict[str, Any]) -> JellyfinRecording | None:
    """Convert a Jellyfin timer into a recording, or None if it will not record."""
    if timer.get("Status") not in ACTIVE_RECORDING_STATUSES:
        return None

    start = _parse_utc_datetime(timer.get("StartDate"))
    end = _parse_utc_datetime(timer.get("EndDate"))
    if start is None or end is None or end <= start:
        LOGGER.debug("Ignoring timer without a valid time range: %s", timer)
        return None

    program_info: dict[str, Any] = timer.get("ProgramInfo") or {}

    return JellyfinRecording(
        timer_id=timer["Id"],
        name=timer["Name"],
        episode_title=program_info.get("EpisodeTitle"),
        channel_name=timer.get("ChannelName"),
        overview=timer.get("Overview"),
        status=timer["Status"],
        start=start - timedelta(seconds=timer.get("PrePaddingSeconds", 0)),
        end=end + timedelta(seconds=timer.get("PostPaddingSeconds", 0)),
    )


def _parse_utc_datetime(value: str | None) -> datetime | None:
    """Parse a Jellyfin timestamp, which is UTC even when the offset is omitted."""
    if value is None or (parsed := dt_util.parse_datetime(value)) is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
