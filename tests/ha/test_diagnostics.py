"""Tests for the diagnostics module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.ut353bt.const import DOMAIN
from custom_components.ut353bt.coordinator import UT353BTCoordinator
from tests.ha.conftest import SAMPLE_READING, TEST_ADDRESS, TEST_NAME


def _make_entry():
    entry = MagicMock()
    entry.entry_id  = "test_entry"
    entry.unique_id = TEST_ADDRESS
    entry.title     = TEST_NAME
    entry.options   = {}
    return entry


def _make_coordinator(hass, mock_ha_client, mock_bluetooth):
    entry = _make_entry()
    with patch("custom_components.ut353bt.coordinator.UT353BTHAClient", return_value=mock_ha_client):
        coord = UT353BTCoordinator(hass, entry)
        coord._client = mock_ha_client
    return coord, entry


# ---------------------------------------------------------------------------
# async_get_config_entry_diagnostics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_diagnostics_redacts_mac(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """The MAC address must be redacted in the output."""
    from custom_components.ut353bt.diagnostics import async_get_config_entry_diagnostics

    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["address"] != TEST_ADDRESS
    assert "REDACTED" in str(result["address"])


@pytest.mark.asyncio
async def test_diagnostics_last_reading_when_data_set(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """last_reading contains decoded fields when coordinator.data is set."""
    from custom_components.ut353bt.diagnostics import async_get_config_entry_diagnostics

    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    coord.data = SAMPLE_READING
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord

    result = await async_get_config_entry_diagnostics(hass, entry)

    reading = result["last_reading"]
    assert reading is not None
    assert reading["sound_dba"] == SAMPLE_READING.sound_dba
    assert reading["mode"]  == SAMPLE_READING.mode.value
    assert reading["speed"] == SAMPLE_READING.speed.value
    assert reading["hold"]  == SAMPLE_READING.hold
    assert reading["low_battery"] == SAMPLE_READING.low_battery


@pytest.mark.asyncio
async def test_diagnostics_last_reading_none_when_no_data(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """last_reading is None before the first successful poll."""
    from custom_components.ut353bt.diagnostics import async_get_config_entry_diagnostics

    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    coord.data = None
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["last_reading"] is None
