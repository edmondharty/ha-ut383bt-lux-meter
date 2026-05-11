"""Tests for diagnostic sensor entities."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ut353bt.const import (
    CONN_STATUS_CONNECTED,
    CONN_STATUS_CONNECTING,
    CONN_STATUS_DISCONNECTED,
    DOMAIN,
)
from custom_components.ut353bt.coordinator import UT353BTCoordinator
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH

from custom_components.ut353bt.sensor import (
    ConnectionStatusSensor,
    LastSeenSensor,
    RSSISensor,
    SoundLevelSensor,
)
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
# ConnectionStatusSensor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_status_connected(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    mock_ha_client.connection_status = CONN_STATUS_CONNECTED
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    sensor = ConnectionStatusSensor(coord, entry)
    assert sensor.native_value == CONN_STATUS_CONNECTED
    assert sensor.available is True


@pytest.mark.asyncio
async def test_connection_status_connecting(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    mock_ha_client.connection_status = CONN_STATUS_CONNECTING
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    sensor = ConnectionStatusSensor(coord, entry)
    assert sensor.native_value == CONN_STATUS_CONNECTING


@pytest.mark.asyncio
async def test_connection_status_no_client(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    coord._client = None
    sensor = ConnectionStatusSensor(coord, entry)
    assert sensor.native_value == CONN_STATUS_DISCONNECTED
    assert sensor.available is True


# ---------------------------------------------------------------------------
# RSSISensor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rssi_returns_value(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    sensor = RSSISensor(coord, entry)
    assert sensor.native_value == -72


@pytest.mark.asyncio
async def test_rssi_none_when_no_service_info(hass, mock_ble_device, mock_ha_client):
    """RSSI is None when the Bluetooth registry has no service info."""
    with patch(
        "custom_components.ut353bt.coordinator.bluetooth.async_ble_device_from_address",
        return_value=mock_ble_device,
    ), patch(
        "custom_components.ut353bt.coordinator.bluetooth.async_last_service_info",
        return_value=None,
    ):
        coord, entry = _make_coordinator(hass, mock_ha_client, None)
        sensor = RSSISensor(coord, entry)
        assert sensor.native_value is None


# ---------------------------------------------------------------------------
# LastSeenSensor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_seen_none_before_first_reading(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    mock_ha_client.last_seen_at = None
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    sensor = LastSeenSensor(coord, entry)
    assert sensor.native_value is None
    assert sensor.available is True


@pytest.mark.asyncio
async def test_last_seen_returns_datetime(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    ts = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    mock_ha_client.last_seen_at = ts
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    sensor = LastSeenSensor(coord, entry)
    assert sensor.native_value == ts


@pytest.mark.asyncio
async def test_last_seen_none_when_no_client(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    coord._client = None
    sensor = LastSeenSensor(coord, entry)
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# SoundLevelSensor — device_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sound_level_device_info_has_bluetooth_connection(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    coord, entry = _make_coordinator(hass, mock_ha_client, mock_bluetooth)
    sensor = SoundLevelSensor(coord, entry)
    assert (CONNECTION_BLUETOOTH, TEST_ADDRESS) in sensor.device_info["connections"]
