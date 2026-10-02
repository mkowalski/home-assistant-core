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
    snapshot: SnapshotAssertion,
) -> None:
    """Test the calendar.get_events action skips timers that will not record."""
    freezer.move_to(NOW)

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
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE

    mock_api.get_live_tv_timers.configure_mock(
        side_effect=None, return_value=load_json_fixture("live-tv-timers.json")
    )
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON


async def test_unauthorized_starts_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a revoked token starting a reauth flow."""
    freezer.move_to(NOW)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_api.get_live_tv_timers.side_effect = HTTPException("Unauthorized", "error")
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
