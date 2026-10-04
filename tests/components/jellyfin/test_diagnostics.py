"""Test Jellyfin diagnostics."""

from unittest.mock import MagicMock

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant

from . import load_json_fixture

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator


async def test_diagnostics(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    snapshot: SnapshotAssertion,
) -> None:
    """Test generating diagnostics for a config entry."""
    data = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert data["entry"]["data"]["client_device_id"] == init_integration.entry_id
    data["entry"]["data"]["client_device_id"] = "entry-id"

    assert data == snapshot


@pytest.mark.usefixtures("mock_jellyfin")
async def test_diagnostics_without_live_tv(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    hass_client: ClientSessionGenerator,
) -> None:
    """Test diagnostics remain available when the user has no Live TV access."""
    mock_api.get_live_tv_info.return_value = load_json_fixture(
        "live-tv-info-other-user.json"
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    data = await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)

    assert data["live_tv"] is None
    assert data["server"]["id"] == "SERVER-UUID"
    assert data["sessions"]
