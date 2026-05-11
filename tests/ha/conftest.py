"""Shared fixtures for HA integration tests.

Uses ``pytest-homeassistant-custom-component`` which provides the
``hass`` fixture and the full HA test infrastructure without needing a
running HA instance.

Run with:
    conda activate ha-ut353bt
    pytest tests/ha/ -v
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import mock_config_flow

import custom_components.ut353bt.config_flow as _cf_module
from custom_components.ut353bt.config_flow import UT353BTConfigFlow
from custom_components.ut353bt.const import DOMAIN
from custom_components.ut353bt.protocol import Mode, SoundReading, Speed

# ---------------------------------------------------------------------------
# Sample readings
# ---------------------------------------------------------------------------

SAMPLE_READING = SoundReading(
    sound_dba=55.3,
    unit="dBA",
    hold=False,
    low_battery=False,
    mode=Mode.NORMAL,
    speed=Speed.FAST,
    status_word=0,
)

SAMPLE_READING_HOLD = SoundReading(
    sound_dba=55.3,
    unit="dBA",
    hold=True,
    low_battery=False,
    mode=Mode.NORMAL,
    speed=Speed.FAST,
    status_word=0,
)

SAMPLE_READING_LOW_BATT = SoundReading(
    sound_dba=48.1,
    unit="dBA",
    hold=False,
    low_battery=True,
    mode=Mode.MAX,
    speed=Speed.SLOW,
    status_word=0,
)

# ---------------------------------------------------------------------------
# Device stub
# ---------------------------------------------------------------------------

TEST_ADDRESS = "AA:BB:CC:DD:EE:FF"
TEST_NAME    = "UT353BT"


@pytest.fixture
def mock_ble_device() -> BLEDevice:
    """Return a fake BLEDevice for the meter."""
    device = MagicMock(spec=BLEDevice)
    device.address = TEST_ADDRESS
    device.name    = TEST_NAME
    return device


# ---------------------------------------------------------------------------
# UT353BTHAClient stub
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ha_client(mock_ble_device: BLEDevice) -> AsyncMock:
    """Return an AsyncMock that replaces UT353BTHAClient."""
    client = AsyncMock()
    client.is_connected      = True
    client.connection_status = "Connected"
    client.last_seen_at      = None
    client.poll              = AsyncMock(return_value=SAMPLE_READING)
    client.set_speed         = AsyncMock()
    client.set_mode          = AsyncMock()
    client.set_hold          = AsyncMock()
    client.connect           = AsyncMock()
    client.disconnect        = AsyncMock()
    client.update_ble_device = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Bluetooth registry stub
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bluetooth(mock_ble_device: BLEDevice):
    """Patch the HA bluetooth lookups used by the coordinator."""
    service_info = MagicMock()
    service_info.rssi = -72
    with (
        patch(
            "custom_components.ut353bt.coordinator.bluetooth.async_ble_device_from_address",
            return_value=mock_ble_device,
        ),
        patch(
            "custom_components.ut353bt.coordinator.bluetooth.async_last_service_info",
            return_value=service_info,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Config-flow test helper
# ---------------------------------------------------------------------------

@contextmanager
def flow_ctx(hass: HomeAssistant) -> Iterator[None]:
    """Context manager that makes the ut353bt config flow findable by HA's loader.

    HA checks ``hass.data['components']['ut353bt.config_flow']`` before looking
    in ``config_entries.HANDLERS``.  We seed both so that ``async_init`` and
    ``async_configure`` work without a full integration load.

    We also patch ``_support_single_config_entry_only`` (called when HA tries
    to prevent duplicate entries) to avoid a second integration-loader round-trip
    that would also fail.
    """
    hass.data.setdefault("components", {})["ut353bt.config_flow"] = _cf_module
    with mock_config_flow(DOMAIN, UT353BTConfigFlow), patch(
        "homeassistant.config_entries._support_single_config_entry_only",
        return_value=False,
    ):
        yield
    hass.data["components"].pop("ut353bt.config_flow", None)
