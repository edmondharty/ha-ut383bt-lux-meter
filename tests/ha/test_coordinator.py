"""Tests for UT353BTCoordinator.

All BLE I/O and HA Bluetooth lookups are mocked — no hardware required.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ut353bt.const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from custom_components.ut353bt.coordinator import UT353BTCoordinator
from custom_components.ut353bt.protocol import Mode, SoundReading, Speed
from tests.ha.conftest import SAMPLE_READING, TEST_ADDRESS, TEST_NAME


def _make_entry(options: dict | None = None):
    entry = MagicMock()
    entry.entry_id  = "test_entry"
    entry.unique_id = TEST_ADDRESS
    entry.title     = TEST_NAME
    entry.options   = options or {}
    return entry


@pytest.mark.asyncio
async def test_coordinator_poll_success(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """Coordinator returns SoundReading from the client on a successful poll."""
    entry = _make_entry()

    with patch("custom_components.ut353bt.coordinator.UT353BTHAClient", return_value=mock_ha_client):
        coordinator = UT353BTCoordinator(hass, entry)
        await coordinator.async_setup()
        result = await coordinator._async_update_data()

    assert result == SAMPLE_READING
    mock_ha_client.poll.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_reconnects_on_poll(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """poll() is called even after a timeout on the first attempt via client retry logic."""
    entry = _make_entry()

    # First call raises TimeoutError; second returns a reading
    mock_ha_client.poll = AsyncMock(
        side_effect=[asyncio.TimeoutError(), SAMPLE_READING]
    )

    with patch("custom_components.ut353bt.coordinator.UT353BTHAClient", return_value=mock_ha_client):
        coordinator = UT353BTCoordinator(hass, entry)
        await coordinator.async_setup()

        from homeassistant.helpers.update_coordinator import UpdateFailed
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_apply_options_updates_interval(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """apply_options() reconfigures the update_interval from entry.options."""
    entry = _make_entry(options={CONF_POLL_INTERVAL: 60})

    with patch("custom_components.ut353bt.coordinator.UT353BTHAClient", return_value=mock_ha_client):
        coordinator = UT353BTCoordinator(hass, entry)
        await coordinator.async_setup()
        coordinator.apply_options()
        await coordinator.async_shutdown()

    assert coordinator.update_interval == timedelta(seconds=60)


@pytest.mark.asyncio
async def test_coordinator_default_interval(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """Coordinator uses DEFAULT_POLL_INTERVAL when no options are set."""
    entry = _make_entry()

    with patch("custom_components.ut353bt.coordinator.UT353BTHAClient", return_value=mock_ha_client):
        coordinator = UT353BTCoordinator(hass, entry)
        await coordinator.async_setup()

    assert coordinator.update_interval == timedelta(seconds=DEFAULT_POLL_INTERVAL)


@pytest.mark.asyncio
async def test_coordinator_shutdown_disconnects_client(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """async_shutdown() calls disconnect() on the client."""
    entry = _make_entry()

    with patch("custom_components.ut353bt.coordinator.UT353BTHAClient", return_value=mock_ha_client):
        coordinator = UT353BTCoordinator(hass, entry)
        await coordinator.async_setup()
        await coordinator.async_shutdown()

    mock_ha_client.disconnect.assert_called_once()
    assert coordinator._client is None
