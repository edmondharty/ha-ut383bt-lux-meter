"""Tests for UT353BTHAClient (ha_client.py).

All BLE operations are mocked — no hardware or bleak install required
(as long as bleak is importable).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from bleak.backends.device import BLEDevice

from custom_components.ut353bt.ha_client import UT353BTHAClient
from custom_components.ut353bt.protocol import (
    CMD_FAST,
    CMD_HOLD,
    CMD_MAX,
    CMD_MIN,
    CMD_QUERY,
    CMD_SLOW,
    Mode,
    SoundReading,
    Speed,
)
from tests.ha.conftest import SAMPLE_READING, TEST_ADDRESS, TEST_NAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ble_device() -> MagicMock:
    dev = MagicMock(spec=BLEDevice)
    dev.address = TEST_ADDRESS
    dev.name    = TEST_NAME
    return dev


def _make_bleak_client(mock_write: AsyncMock | None = None) -> MagicMock:
    """Return a fake BleakClientWithServiceCache."""
    client        = MagicMock()
    client.is_connected   = True
    client.start_notify   = AsyncMock()
    client.stop_notify    = AsyncMock()
    client.disconnect     = AsyncMock()
    client.write_gatt_char = mock_write or AsyncMock()
    return client


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_subscribes_to_notifications():
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device, poll_timeout=1.0)
        await client.connect()

    bleak_client.start_notify.assert_called_once()
    assert client.is_connected


@pytest.mark.asyncio
async def test_disconnect_stops_notify_and_disconnects():
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device, poll_timeout=1.0)
        await client.connect()
        await client.disconnect()

    # stop_notify is called twice: once in connect() to clear stale BlueZ state,
    # and once in disconnect() to cleanly unsubscribe.
    assert bleak_client.stop_notify.call_count == 2
    bleak_client.disconnect.assert_called_once()
    assert not client.is_connected


# ---------------------------------------------------------------------------
# poll()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_sends_query_and_returns_reading():
    ble_device   = _make_ble_device()
    write_mock   = AsyncMock()
    bleak_client = _make_bleak_client(write_mock)

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device, poll_timeout=1.0)
        await client.connect()

        # Inject the reading via write side-effect so it arrives *after*
        # poll() drains stale queue items and sends CMD_QUERY.
        async def _inject(*args, **kwargs):
            client._queue.put_nowait(SAMPLE_READING)

        write_mock.side_effect = _inject
        result = await client.poll()

    assert result == SAMPLE_READING
    write_mock.assert_called_once_with(
        "0000ff01-0000-1000-8000-00805f9b34fb", CMD_QUERY, response=False
    )


@pytest.mark.asyncio
async def test_poll_drains_stale_readings():
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()
    fresh_reading = SoundReading(
        sound_dba=70.0, unit="dBA", hold=False,
        low_battery=False, mode=Mode.NORMAL, speed=Speed.FAST, status_word=0
    )

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device, poll_timeout=1.0)
        await client.connect()

        # Pre-load a stale reading, then enqueue the fresh one after the write
        client._queue.put_nowait(SAMPLE_READING)  # stale

        async def _side_effect(*a, **kw):
            client._queue.put_nowait(fresh_reading)

        bleak_client.write_gatt_char.side_effect = _side_effect
        result = await client.poll()

    assert result == fresh_reading


@pytest.mark.asyncio
async def test_poll_timeout_raises():
    """poll() raises TimeoutError if both attempts (wake-up + retry) time out."""
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = UT353BTHAClient(ble_device, poll_timeout=0.1)
        await client.connect()

        with pytest.raises(asyncio.TimeoutError):
            await client.poll()


@pytest.mark.asyncio
async def test_poll_retries_after_wakeup_timeout():
    """poll() reconnects and succeeds after the first CMD_QUERY times out."""
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()
    reading      = SAMPLE_READING

    call_count = 0

    async def _write_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            # Second write (after reconnect) — put a reading in the queue
            bleak_client._notification_handler(None, b"")

    bleak_client.write_gatt_char.side_effect = _write_side_effect

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = UT353BTHAClient(ble_device, poll_timeout=0.1)
        await client.connect()

        # Pre-load the queue so the second _query_once returns immediately
        client._queue.put_nowait(reading)
        # But first _query_once must drain it — patch it to not drain on first call
        # Simpler: just verify the retry path by having _query_once return None first.
        original_query_once = client._query_once
        calls = []

        async def _patched_query_once():
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                return None  # simulate first timeout
            return reading

        client._query_once = _patched_query_once
        result = await client.poll()

    assert result == reading
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_speed_fast():
    ble_device   = _make_ble_device()
    write_mock   = AsyncMock()
    bleak_client = _make_bleak_client(write_mock)

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device)
        await client.connect()
        await client.set_speed(Speed.FAST)

    write_mock.assert_called_with(
        "0000ff01-0000-1000-8000-00805f9b34fb", CMD_FAST, response=False
    )


@pytest.mark.asyncio
async def test_set_speed_slow():
    ble_device   = _make_ble_device()
    write_mock   = AsyncMock()
    bleak_client = _make_bleak_client(write_mock)

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device)
        await client.connect()
        await client.set_speed(Speed.SLOW)

    write_mock.assert_called_with(
        "0000ff01-0000-1000-8000-00805f9b34fb", CMD_SLOW, response=False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("current,target,expected_cmds", [
    (Mode.NORMAL, Mode.MAX,    [CMD_MAX]),
    (Mode.NORMAL, Mode.MIN,    [CMD_MAX, CMD_MIN]),
    (Mode.MAX,    Mode.MIN,    [CMD_MIN]),
    (Mode.MAX,    Mode.NORMAL, [CMD_MIN, CMD_MIN]),
    (Mode.MIN,    Mode.NORMAL, [CMD_MIN]),
    (Mode.MIN,    Mode.MAX,    [CMD_MIN, CMD_MAX]),
])
async def test_set_mode_transitions(current, target, expected_cmds):
    ble_device   = _make_ble_device()
    write_mock   = AsyncMock()
    bleak_client = _make_bleak_client(write_mock)
    reading_with_mode = SoundReading(
        sound_dba=50.0, unit="dBA", hold=False,
        low_battery=False, mode=current, speed=Speed.FAST, status_word=0
    )

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device)
        await client.connect()
        client._last_reading = reading_with_mode

        with patch("asyncio.sleep", AsyncMock()):
            await client.set_mode(target)

    calls = [
        call("0000ff01-0000-1000-8000-00805f9b34fb", cmd, response=False)
        for cmd in expected_cmds
    ]
    write_mock.assert_has_calls(calls, any_order=False)


@pytest.mark.asyncio
async def test_set_hold_sends_command_when_state_differs():
    ble_device   = _make_ble_device()
    write_mock   = AsyncMock()
    bleak_client = _make_bleak_client(write_mock)

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device)
        await client.connect()
        # Last reading has hold=False; we want to enable hold
        client._last_reading = SAMPLE_READING
        await client.set_hold(True)

    write_mock.assert_called_with(
        "0000ff01-0000-1000-8000-00805f9b34fb", CMD_HOLD, response=False
    )


@pytest.mark.asyncio
async def test_set_hold_skips_command_when_state_same():
    ble_device   = _make_ble_device()
    write_mock   = AsyncMock()
    bleak_client = _make_bleak_client(write_mock)

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device)
        await client.connect()
        client._last_reading = SAMPLE_READING  # hold=False
        write_mock.reset_mock()
        await client.set_hold(False)  # already False — no command sent

    write_mock.assert_not_called()


# ---------------------------------------------------------------------------
# connection_status property
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_status_connected():
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device)
        await client.connect()

    from custom_components.ut353bt.const import CONN_STATUS_CONNECTED
    assert client.connection_status == CONN_STATUS_CONNECTED


@pytest.mark.asyncio
async def test_connection_status_disconnected():
    ble_device = _make_ble_device()
    client = UT353BTHAClient(ble_device)

    from custom_components.ut353bt.const import CONN_STATUS_DISCONNECTED
    assert client.connection_status == CONN_STATUS_DISCONNECTED


@pytest.mark.asyncio
async def test_connection_status_connecting():
    """_connecting=True while establish_connection is in-flight."""
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()
    captured: list[str] = []

    async def fake_establish(*args, **kwargs):
        from custom_components.ut353bt.const import CONN_STATUS_CONNECTING
        captured.append(client.connection_status)
        return bleak_client

    client = UT353BTHAClient(ble_device)
    with patch("custom_components.ut353bt.ha_client.establish_connection", side_effect=fake_establish):
        await client.connect()

    from custom_components.ut353bt.const import CONN_STATUS_CONNECTING
    assert captured == [CONN_STATUS_CONNECTING]


# ---------------------------------------------------------------------------
# last_seen_at property
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_seen_at_none_before_poll():
    ble_device = _make_ble_device()
    client = UT353BTHAClient(ble_device)
    assert client.last_seen_at is None


@pytest.mark.asyncio
async def test_last_seen_at_set_after_successful_poll():
    ble_device   = _make_ble_device()
    bleak_client = _make_bleak_client()

    async def inject_reading(*args, **kwargs):
        """Simulate device responding after CMD_QUERY is written."""
        bleak_client._client_ref._queue.put_nowait(SAMPLE_READING)

    with patch(
        "custom_components.ut353bt.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ):
        client = UT353BTHAClient(ble_device, poll_timeout=1.0)
        bleak_client._client_ref = client
        bleak_client.write_gatt_char = AsyncMock(side_effect=inject_reading)
        await client.connect()
        await client.poll()

    from datetime import timezone
    assert client.last_seen_at is not None
    assert client.last_seen_at.tzinfo == timezone.utc
