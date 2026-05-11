"""Live BLE integration test for the UT353BT.

Requires the physical meter to be powered on with Bluetooth enabled.

Skip by default — opt in with:
    conda activate ha-ut353bt
    pytest -m live --live -v

macOS note: Terminal (or your IDE) may need Bluetooth permission.
Go to System Settings → Privacy & Security → Bluetooth.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from custom_components.ut353bt.ha_client import UT353BTHAClient
from custom_components.ut353bt.protocol import Mode, Speed

DEVICE_NAME  = "UT353BT"
SCAN_TIMEOUT = 12.0  # seconds

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def use_corebluetooth_backend():
    """Restore platform.system → 'Darwin' for live BLE tests.

    pytest-homeassistant-custom-component patches it to 'Linux' for the whole
    session (to drive HA's bluetooth mocks), which causes bleak to select the
    BlueZ/dbus backend on macOS.  This fixture counter-patches it back so
    bleak uses CoreBluetooth.
    """
    with patch("platform.system", return_value="Darwin"):
        yield


@pytest.fixture
async def ble_device() -> BLEDevice:
    """Scan for the UT353BT and return a BLEDevice, or skip if not found."""
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=SCAN_TIMEOUT)
    if device is None:
        pytest.skip(
            f"'{DEVICE_NAME}' not found within {SCAN_TIMEOUT:.0f} s. "
            "Make sure the meter is powered on with Bluetooth enabled."
        )
    return device


@pytest.fixture
async def connected_client(ble_device: BLEDevice) -> UT353BTHAClient:
    """Return a connected UT353BTHAClient; disconnect after the module."""
    client = UT353BTHAClient(ble_device, poll_timeout=8.0)
    await client.connect()
    yield client
    await client.disconnect()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_device_found(ble_device: BLEDevice) -> None:
    """The scanner finds a device with the expected name."""
    assert ble_device.name == DEVICE_NAME
    assert ble_device.address  # non-empty MAC / UUID


async def test_poll_returns_valid_reading(connected_client: UT353BTHAClient) -> None:
    """A single poll returns a well-formed SoundReading."""
    reading = await connected_client.poll()

    assert 20.0 <= reading.sound_dba <= 130.0, (
        f"sound_dba {reading.sound_dba} outside plausible range"
    )
    assert reading.unit == "dBA"
    assert reading.mode in (Mode.NORMAL, Mode.MAX, Mode.MIN)
    assert reading.speed in (Speed.FAST, Speed.SLOW)
    assert isinstance(reading.hold, bool)
    assert isinstance(reading.low_battery, bool)


async def test_set_speed_fast(connected_client: UT353BTHAClient) -> None:
    """set_speed(FAST) is accepted without error; next poll reflects it."""
    await connected_client.set_speed(Speed.FAST)
    reading = await connected_client.poll()
    assert reading.speed == Speed.FAST


async def test_set_speed_slow(connected_client: UT353BTHAClient) -> None:
    """set_speed(SLOW) is accepted without error; next poll reflects it."""
    await connected_client.set_speed(Speed.SLOW)
    reading = await connected_client.poll()
    assert reading.speed == Speed.SLOW


async def test_hold_toggle(connected_client: UT353BTHAClient) -> None:
    """Enabling then disabling hold round-trips correctly."""
    # Poll first so the client knows the actual device state before toggling.
    reading = await connected_client.poll()

    # Ensure we start without hold, regardless of prior test state.
    if reading.hold:
        await connected_client.set_hold(False)
        reading = await connected_client.poll()
    assert reading.hold is False

    await connected_client.set_hold(True)
    reading = await connected_client.poll()
    assert reading.hold is True

    await connected_client.set_hold(False)
    reading = await connected_client.poll()
    assert reading.hold is False


async def test_mode_cycle_normal_max_min(connected_client: UT353BTHAClient) -> None:
    """Cycling through Normal → Max → Min → Normal works end-to-end."""
    # Poll first so the client knows the actual device state before any transition.
    await connected_client.poll()

    # Return to Normal first (idempotent if already there)
    await connected_client.set_mode(Mode.NORMAL)
    assert (await connected_client.poll()).mode == Mode.NORMAL

    await connected_client.set_mode(Mode.MAX)
    assert (await connected_client.poll()).mode == Mode.MAX

    await connected_client.set_mode(Mode.MIN)
    assert (await connected_client.poll()).mode == Mode.MIN

    await connected_client.set_mode(Mode.NORMAL)
    assert (await connected_client.poll()).mode == Mode.NORMAL
