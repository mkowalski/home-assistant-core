"""Tests for the Jellyfin calendar platform."""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from jellyfin_apiclient_python.exceptions import HTTPException
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.calendar import (
    DOMAIN as CALENDAR_DOMAIN,
    SERVICE_GET_EVENTS,
)
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import load_json_fixture

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform

ENTITY_ID = "calendar.jellyfin_server_recordings"
NOW = "2026-10-02T20:00:00+00:00"


@pytest.fixture(autouse=True)
async def set_time_zone(hass: HomeAssistant) -> None:
    """Use UTC so the event times in the fixtures are easy to follow."""
    await hass.config.async_set_time_zone("UTC")


async def test_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the calendar entity while a recording is in progress."""
    freezer.move_to(NOW)

    mock_config_entry.add_to_hass(hass)
    with patch("homeassistant.components.jellyfin.PLATFORMS", [Platform.CALENDAR]):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_state_follows_recordings(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
) -> None:
    """Test the state moving from an in-progress to the next scheduled recording."""
    freezer.move_to(NOW)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON
    assert state.attributes["message"] == "Evening News - Friday edition"
    assert state.attributes["start_time"] == "2026-10-02 19:50:00"
    assert state.attributes["end_time"] == "2026-10-02 20:30:00"

    # The in-progress recording ends at 20:30; the next one starts at 21:00
    # with 120 seconds of pre-padding
    freezer.move_to("2026-10-02T20:45:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_OFF
    assert state.attributes["message"] == "Blockbuster Night"
    assert state.attributes["start_time"] == "2026-10-02 20:58:00"
    assert state.attributes["end_time"] == "2026-10-02 22:05:00"

    freezer.move_to("2026-10-02T20:59:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON
    assert state.attributes["message"] == "Blockbuster Night"

    freezer.move_to("2026-10-10T00:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_OFF
    assert "message" not in state.attributes


async def test_no_recordings(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test the calendar entity without any scheduled recordings."""
    freezer.move_to(NOW)
    mock_api.get_live_tv_timers.return_value = load_json_fixture(
        "live-tv-timers-empty.json"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_OFF
    assert "message" not in state.attributes


async def test_get_events(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the calendar.get_events action skips timers that will not record."""
    freezer.move_to(NOW)
    mock_api.get_live_tv_timers.return_value["Items"].reverse()

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        SERVICE_GET_EVENTS,
        {
            "entity_id": ENTITY_ID,
            "start_date_time": datetime(2026, 10, 1).isoformat(),
            "end_date_time": datetime(2026, 10, 15).isoformat(),
        },
        blocking=True,
        return_response=True,
    )

    assert response == snapshot
    events = response[ENTITY_ID]["events"]
    assert [event["summary"] for event in events] == [
        "Evening News - Friday edition",
        "Blockbuster Night",
        "Late Game",
        "Weekly Documentary",
    ]


@pytest.mark.parametrize(
    ("start_date_time", "end_date_time", "expected_summaries"),
    [
        pytest.param(
            "2026-10-02T19:45:00+00:00",
            "2026-10-02T20:00:00+00:00",
            ["Evening News - Friday edition"],
            id="ends_after_window",
        ),
        pytest.param(
            "2026-10-02T20:00:00+00:00",
            "2026-10-02T20:45:00+00:00",
            ["Evening News - Friday edition"],
            id="starts_before_window",
        ),
        pytest.param(
            "2026-10-02T20:30:00+00:00",
            "2026-10-02T20:58:00+00:00",
            [],
            id="exclusive_bounds",
        ),
        pytest.param(
            "2026-10-02T22:00:00+02:00",
            "2026-10-02T22:45:00+02:00",
            ["Evening News - Friday edition"],
            id="query_with_utc_offset",
        ),
        pytest.param(
            "2026-10-09T20:14:00+00:00",
            "2026-10-09T20:15:00+00:00",
            ["Weekly Documentary"],
            id="offsetless_timer_is_utc",
        ),
    ],
)
@pytest.mark.usefixtures("mock_jellyfin")
async def test_get_events_time_range(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    start_date_time: str,
    end_date_time: str,
    expected_summaries: list[str],
) -> None:
    """Test partial overlaps and exclusive boundaries when querying recordings."""
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Europe/Berlin")

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        SERVICE_GET_EVENTS,
        {
            "entity_id": ENTITY_ID,
            "start_date_time": start_date_time,
            "end_date_time": end_date_time,
        },
        blocking=True,
        return_response=True,
    )

    assert response is not None
    assert [event["summary"] for event in response[ENTITY_ID]["events"]] == (
        expected_summaries
    )


@pytest.mark.parametrize(
    ("status", "expected_events"),
    [
        pytest.param(
            "ConflictedOk",
            [("Evening News - Friday edition", "confirmed")],
            id="resolved_conflict",
        ),
        pytest.param("Completed", [], id="completed"),
    ],
)
@pytest.mark.usefixtures("mock_jellyfin")
async def test_get_events_recording_status(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    status: str,
    expected_events: list[tuple[str, str]],
) -> None:
    """Test resolved conflicts are confirmed and completed recordings are omitted."""
    freezer.move_to(NOW)
    timers = mock_api.get_live_tv_timers.return_value
    timer = timers["Items"][0]
    timer["Status"] = status
    timers["Items"] = [timer]
    timers["TotalRecordCount"] = 1

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        SERVICE_GET_EVENTS,
        {
            "entity_id": ENTITY_ID,
            "start_date_time": "2026-10-02T19:00:00+00:00",
            "end_date_time": "2026-10-02T21:00:00+00:00",
        },
        blocking=True,
        return_response=True,
    )

    assert response is not None
    assert [
        (event["summary"], event["status"]) for event in response[ENTITY_ID]["events"]
    ] == expected_events


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        pytest.param(None, "2026-10-02T20:30:00Z", id="missing_start"),
        pytest.param("2026-10-02T19:50:00Z", None, id="missing_end"),
        pytest.param("not-a-date", "2026-10-02T20:30:00Z", id="invalid_start"),
        pytest.param("2026-10-02T20:00:00Z", "2026-10-02T20:00:00Z", id="empty_range"),
        pytest.param(
            "2026-10-02T20:15:00Z", "2026-10-02T20:00:00Z", id="reversed_range"
        ),
    ],
)
@pytest.mark.usefixtures("mock_jellyfin")
async def test_get_events_invalid_timer_range(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    start_date: str | None,
    end_date: str | None,
) -> None:
    """Test invalid timer ranges are skipped without hiding valid recordings."""
    freezer.move_to(NOW)
    timer = mock_api.get_live_tv_timers.return_value["Items"][0]
    timer["StartDate"] = start_date
    timer["EndDate"] = end_date

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        SERVICE_GET_EVENTS,
        {
            "entity_id": ENTITY_ID,
            "start_date_time": "2026-10-02T19:00:00+00:00",
            "end_date_time": "2026-10-02T21:00:00+00:00",
        },
        blocking=True,
        return_response=True,
    )

    assert response is not None
    assert [event["summary"] for event in response[ENTITY_ID]["events"]] == [
        "Blockbuster Night"
    ]


@pytest.mark.parametrize(
    "mock_kwargs",
    [
        pytest.param(
            {"side_effect": HTTPException("ServerUnreachable", "error")},
            id="exception",
        ),
        pytest.param({"return_value": None}, id="server_error"),
    ],
)
async def test_update_failed(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
    mock_kwargs: dict[str, Any],
) -> None:
    """Test the calendar entity becoming unavailable and recovering."""
    freezer.move_to(NOW)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON

    mock_api.get_live_tv_timers.configure_mock(**mock_kwargs)
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE

    mock_api.get_live_tv_timers.configure_mock(
        side_effect=None, return_value=load_json_fixture("live-tv-timers.json")
    )
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON


@pytest.mark.parametrize("failing_method", ["sessions", "get_live_tv_timers"])
async def test_unauthorized_starts_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
    failing_method: str,
) -> None:
    """Test a revoked token starting a reauth flow."""
    freezer.move_to(NOW)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    getattr(mock_api, failing_method).side_effect = HTTPException(
        "Unauthorized", "error"
    )
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
