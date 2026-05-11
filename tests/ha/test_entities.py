"""Tests for HA entities (sensor, binary_sensor, select, switch).

All tests use a mocked coordinator and client — no BLE hardware needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ut353bt.binary_sensor import BatteryLowBinarySensor
from custom_components.ut353bt.coordinator import UT353BTCoordinator
from custom_components.ut353bt.protocol import Mode, Speed
from custom_components.ut353bt.select import ModeSelect, SpeedSelect
from custom_components.ut353bt.sensor import SoundLevelSensor
from custom_components.ut353bt.switch import HoldSwitch
from tests.ha.conftest import (
    SAMPLE_READING,
    SAMPLE_READING_HOLD,
    SAMPLE_READING_LOW_BATT,
    TEST_ADDRESS,
    TEST_NAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(reading=SAMPLE_READING, mock_client=None):
    coordinator = MagicMock(spec=UT353BTCoordinator)
    coordinator.data            = reading
    coordinator.async_request_refresh = AsyncMock()
    coordinator.client          = mock_client or AsyncMock()
    return coordinator


def _make_entry():
    entry = MagicMock()
    entry.unique_id = TEST_ADDRESS
    entry.title     = TEST_NAME
    return entry


# ---------------------------------------------------------------------------
# SoundLevelSensor
# ---------------------------------------------------------------------------

def test_sound_level_sensor_value():
    coordinator = _make_coordinator(SAMPLE_READING)
    entry       = _make_entry()
    sensor      = SoundLevelSensor(coordinator, entry)

    assert sensor.native_value == 55.3


def test_sound_level_sensor_none_when_no_data():
    coordinator = _make_coordinator(None)
    entry       = _make_entry()
    sensor      = SoundLevelSensor(coordinator, entry)

    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# BatteryLowBinarySensor
# ---------------------------------------------------------------------------

def test_battery_sensor_not_low():
    coordinator = _make_coordinator(SAMPLE_READING)
    entry       = _make_entry()
    sensor      = BatteryLowBinarySensor(coordinator, entry)

    assert sensor.is_on is False


def test_battery_sensor_low():
    coordinator = _make_coordinator(SAMPLE_READING_LOW_BATT)
    entry       = _make_entry()
    sensor      = BatteryLowBinarySensor(coordinator, entry)

    assert sensor.is_on is True


# ---------------------------------------------------------------------------
# ModeSelect
# ---------------------------------------------------------------------------

def test_mode_select_current_option_normal():
    coordinator = _make_coordinator(SAMPLE_READING)
    entity      = ModeSelect(coordinator, _make_entry())
    assert entity.current_option == "Normal"


def test_mode_select_current_option_max():
    coordinator = _make_coordinator(SAMPLE_READING_LOW_BATT)  # mode=MAX
    entity      = ModeSelect(coordinator, _make_entry())
    assert entity.current_option == "Max"


@pytest.mark.asyncio
async def test_mode_select_calls_set_mode():
    client      = AsyncMock()
    coordinator = _make_coordinator(SAMPLE_READING, mock_client=client)
    entity      = ModeSelect(coordinator, _make_entry())

    await entity.async_select_option("Max")

    client.set_mode.assert_called_once_with(Mode.MAX)
    coordinator.async_request_refresh.assert_called_once()


# ---------------------------------------------------------------------------
# SpeedSelect
# ---------------------------------------------------------------------------

def test_speed_select_current_option_fast():
    coordinator = _make_coordinator(SAMPLE_READING)  # speed=FAST
    entity      = SpeedSelect(coordinator, _make_entry())
    assert entity.current_option == "Fast"


@pytest.mark.asyncio
async def test_speed_select_calls_set_speed():
    client      = AsyncMock()
    coordinator = _make_coordinator(SAMPLE_READING, mock_client=client)
    entity      = SpeedSelect(coordinator, _make_entry())

    await entity.async_select_option("Slow")

    client.set_speed.assert_called_once_with(Speed.SLOW)
    coordinator.async_request_refresh.assert_called_once()


# ---------------------------------------------------------------------------
# HoldSwitch
# ---------------------------------------------------------------------------

def test_hold_switch_not_held():
    coordinator = _make_coordinator(SAMPLE_READING)
    entity      = HoldSwitch(coordinator, _make_entry())
    assert entity.is_on is False


def test_hold_switch_held():
    coordinator = _make_coordinator(SAMPLE_READING_HOLD)
    entity      = HoldSwitch(coordinator, _make_entry())
    assert entity.is_on is True


@pytest.mark.asyncio
async def test_hold_switch_turn_on():
    client      = AsyncMock()
    coordinator = _make_coordinator(SAMPLE_READING, mock_client=client)
    entity      = HoldSwitch(coordinator, _make_entry())

    await entity.async_turn_on()

    client.set_hold.assert_called_once_with(True)
    coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_hold_switch_turn_off():
    client      = AsyncMock()
    coordinator = _make_coordinator(SAMPLE_READING_HOLD, mock_client=client)
    entity      = HoldSwitch(coordinator, _make_entry())

    await entity.async_turn_off()

    client.set_hold.assert_called_once_with(False)
    coordinator.async_request_refresh.assert_called_once()
