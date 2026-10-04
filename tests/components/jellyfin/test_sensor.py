"""Tests for the Jellyfin sensor platform."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.jellyfin.const import DOMAIN
from homeassistant.components.sensor import ATTR_STATE_CLASS
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_FRIENDLY_NAME,
    ATTR_ICON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import load_json_fixture

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform

NEXT_RECORDING_ENTITY_ID = "sensor.jellyfin_server_next_recording"


async def test_watching(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
    mock_jellyfin: MagicMock,
) -> None:
    """Test the Jellyfin watching sensor."""
    state = hass.states.get("sensor.jellyfin_server_active_clients")
    assert state
    assert state.attributes.get(ATTR_DEVICE_CLASS) is None
    assert state.attributes.get(ATTR_FRIENDLY_NAME) == "JELLYFIN-SERVER Active clients"
    assert state.attributes.get(ATTR_ICON) is None
    assert state.attributes.get(ATTR_STATE_CLASS) is None
    assert state.state == "5"

    entry = entity_registry.async_get(state.entity_id)
    assert entry
    assert entry.device_id
    assert entry.entity_category is None
    assert entry.unique_id == "SERVER-UUID-watching"

    device = device_registry.async_get(entry.device_id)
    assert device
    assert device.configuration_url is None
    assert device.connections == set()
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.hw_version is None
    assert device.identifiers == {(DOMAIN, "SERVER-UUID")}
    assert device.manufacturer == "Jellyfin"
    assert device.name == "JELLYFIN-SERVER"
    assert device.sw_version is None


async def test_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the sensor entities."""
    freezer.move_to("2026-10-02T20:00:00+00:00")
    mock_api.get_live_tv_timers.return_value["Items"].reverse()

    mock_config_entry.add_to_hass(hass)
    with patch("homeassistant.components.jellyfin.PLATFORMS", [Platform.SENSOR]):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.parametrize("status", ["InProgress", "ConflictedOk", "ConflictedNotOk"])
async def test_next_recording(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
    status: str,
) -> None:
    """Test the next recording sensor following the scheduled timers."""
    freezer.move_to("2026-10-02T20:00:00+00:00")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # The in-progress timer is skipped; the next scheduled one starts at
    # 21:00 with 120 seconds of pre-padding
    state = hass.states.get(NEXT_RECORDING_ENTITY_ID)
    assert state
    assert state.state == "2026-10-02T20:58:00+00:00"

    mock_api.get_live_tv_timers.return_value["Items"][1]["Status"] = status
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(NEXT_RECORDING_ENTITY_ID)
    assert state
    assert state.state == "2026-10-09T20:14:00+00:00"

    mock_api.get_live_tv_timers.return_value = load_json_fixture(
        "live-tv-timers-empty.json"
    )
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(NEXT_RECORDING_ENTITY_ID)
    assert state
    assert state.state == STATE_UNKNOWN


async def test_next_recording_unavailable_when_update_fails(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test the next recording sensor becoming unavailable when the server errors."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_api.get_live_tv_timers.return_value = None
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(NEXT_RECORDING_ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE


async def test_no_next_recording_without_live_tv(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_jellyfin: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test only the session sensor exists when Live TV is not available."""
    mock_api.get_live_tv_info.return_value = load_json_fixture(
        "live-tv-info-other-user.json"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.jellyfin_server_active_clients")
    assert hass.states.get(NEXT_RECORDING_ENTITY_ID) is None
