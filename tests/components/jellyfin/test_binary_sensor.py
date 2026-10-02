"""Tests for the Jellyfin binary sensor platform."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import load_json_fixture

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform

ENTITY_ID = "binary_sensor.jellyfin_server_recording"


async def test_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the binary sensor entity while a recording is in progress."""
    mock_config_entry.add_to_hass(hass)
    with patch("homeassistant.components.jellyfin.PLATFORMS", [Platform.BINARY_SENSOR]):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_recording_follows_timer_status(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test the binary sensor turning off once no timer is in progress."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON

    mock_api.get_live_tv_timers.return_value = load_json_fixture(
        "live-tv-timers-empty.json"
    )
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_OFF


async def test_unavailable_when_update_fails(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test the binary sensor becoming unavailable when the server errors."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_api.get_live_tv_timers.return_value = None
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE


async def test_no_entity_without_live_tv(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test no binary sensor is created when Live TV is not available."""
    mock_api.get_live_tv_info.return_value = load_json_fixture(
        "live-tv-info-other-user.json"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID) is None
