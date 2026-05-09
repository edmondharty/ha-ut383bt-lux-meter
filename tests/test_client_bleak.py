"""Unit tests for ut353bt.UT353BTClient.

All BLE I/O is mocked — no hardware required.  The strategy is to inject a
pre-configured mock into client._client and call _on_notification directly to
simulate incoming packets, making the async logic fully exercisable in-process.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from ut353bt.client_bleak import DATA_IN_UUID, DATA_OUT_UUID, UT353BTClient
from ut353bt.protocol import (
    CMD_FAST, CMD_HOLD, CMD_MAX, CMD_MIN, CMD_QUERY, CMD_SLOW,
    SoundReading, Speed, Mode,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

FAST_NORMAL_PACKET = bytes.fromhex("aabb10013b202033362e396442413d34000419")
SLOW_NORMAL_PACKET = bytes.fromhex("aabb10013b202035322e386442413d33000415")


def _mock_ble_client() -> MagicMock:
    """Return a fully mocked BleakClient instance."""
    mock = MagicMock()
    mock.is_connected = True
    mock.connect        = AsyncMock()
    mock.disconnect     = AsyncMock()
    mock.start_notify   = AsyncMock()
    mock.stop_notify    = AsyncMock()
    mock.write_gatt_char = AsyncMock()
    return mock


def _make_connected_client(mock_ble: MagicMock) -> UT353BTClient:
    """Return a UT353BTClient with _client already set to *mock_ble*."""
    client = UT353BTClient()
    client._client = mock_ble
    return client


# ── is_connected property ─────────────────────────────────────────────────────

class TestIsConnected:

    def test_false_before_connect(self):
        client = UT353BTClient()
        assert client.is_connected is False

    def test_true_with_mock_client(self):
        client = _make_connected_client(_mock_ble_client())
        assert client.is_connected is True

    def test_false_when_ble_reports_disconnected(self):
        mock = _mock_ble_client()
        mock.is_connected = False
        client = _make_connected_client(mock)
        assert client.is_connected is False


# ── _assert_connected ─────────────────────────────────────────────────────────

class TestAssertConnected:

    def test_raises_when_not_connected(self):
        client = UT353BTClient()
        with pytest.raises(RuntimeError, match="Not connected"):
            client._assert_connected()

    def test_no_raise_when_connected(self):
        client = _make_connected_client(_mock_ble_client())
        client._assert_connected()  # should not raise


# ── _on_notification ──────────────────────────────────────────────────────────

class TestOnNotification:

    def test_valid_packet_is_queued(self):
        client = UT353BTClient()
        client._on_notification(None, bytearray(FAST_NORMAL_PACKET))
        assert not client._reading_queue.empty()
        reading = client._reading_queue.get_nowait()
        assert isinstance(reading, SoundReading)
        assert reading.sound_dba == pytest.approx(36.9, abs=0.05)

    def test_invalid_packet_is_discarded(self):
        client = UT353BTClient()
        client._on_notification(None, bytearray(b"\xAA\xBB\x00"))  # too short
        assert client._reading_queue.empty()

    def test_ack_packet_is_discarded(self):
        client = UT353BTClient()
        client._on_notification(None, bytearray(bytes.fromhex("aabb04ff000268")))
        assert client._reading_queue.empty()

    def test_multiple_packets_all_queued(self):
        client = UT353BTClient()
        client._on_notification(None, bytearray(FAST_NORMAL_PACKET))
        client._on_notification(None, bytearray(SLOW_NORMAL_PACKET))
        assert client._reading_queue.qsize() == 2


# ── poll ──────────────────────────────────────────────────────────────────────

class TestPoll:

    def test_raises_when_not_connected(self):
        client = UT353BTClient()
        with pytest.raises(RuntimeError):
            asyncio.run(client.poll())

    def test_sends_query_and_returns_reading(self):
        async def _run():
            mock = _mock_ble_client()

            async def fake_write(uuid, data, response):
                # Simulate the device responding to the query.
                client._on_notification(None, bytearray(FAST_NORMAL_PACKET))

            mock.write_gatt_char.side_effect = fake_write
            client = _make_connected_client(mock)
            reading = await client.poll(timeout=2.0)
            assert reading.sound_dba == pytest.approx(36.9, abs=0.05)
            mock.write_gatt_char.assert_called_once_with(
                DATA_IN_UUID, CMD_QUERY, response=False
            )

        asyncio.run(_run())

    def test_drains_stale_readings_before_query(self):
        async def _run():
            mock = _mock_ble_client()
            client = _make_connected_client(mock)

            # Pre-load a stale reading into the queue.
            stale = bytearray(SLOW_NORMAL_PACKET)
            client._reading_queue.put_nowait(
                __import__("ut353bt.protocol", fromlist=["parse_packet"]).parse_packet(stale)
            )

            # After poll drains the queue and sends the query, inject fresh data.
            async def fake_write(uuid, data, response):
                client._on_notification(None, bytearray(FAST_NORMAL_PACKET))

            mock.write_gatt_char.side_effect = fake_write
            reading = await client.poll(timeout=2.0)
            # Should receive the FAST packet, not the stale SLOW one.
            assert reading.speed == Speed.FAST

        asyncio.run(_run())

    def test_raises_timeout_if_no_response(self):
        async def _run():
            mock = _mock_ble_client()
            client = _make_connected_client(mock)
            with pytest.raises(asyncio.TimeoutError):
                await client.poll(timeout=0.05)

        asyncio.run(_run())


# ── stream ────────────────────────────────────────────────────────────────────

class TestStream:

    def test_yields_requested_count(self):
        async def _run():
            mock = _mock_ble_client()
            client = _make_connected_client(mock)

            async def fake_write(uuid, data, response):
                client._on_notification(None, bytearray(FAST_NORMAL_PACKET))

            mock.write_gatt_char.side_effect = fake_write
            readings = []
            async for r in client.stream(interval=0, count=3):
                readings.append(r)

            assert len(readings) == 3
            assert all(isinstance(r, SoundReading) for r in readings)

        asyncio.run(_run())

    def test_raises_when_not_connected(self):
        async def _run():
            client = UT353BTClient()
            with pytest.raises(RuntimeError):
                async for _ in client.stream(count=1):
                    pass

        asyncio.run(_run())


# ── control commands ──────────────────────────────────────────────────────────

class TestControlCommands:

    def _run_control(self, method_name: str, expected_cmd: bytes) -> None:
        async def _run():
            mock = _mock_ble_client()
            client = _make_connected_client(mock)
            await getattr(client, method_name)()
            mock.write_gatt_char.assert_called_once_with(
                DATA_IN_UUID, expected_cmd, response=False
            )

        asyncio.run(_run())

    def test_set_slow_sends_correct_command(self):
        self._run_control("set_slow", CMD_SLOW)

    def test_set_fast_sends_correct_command(self):
        self._run_control("set_fast", CMD_FAST)

    def test_set_max_mode_sends_correct_command(self):
        self._run_control("set_max_mode", CMD_MAX)

    def test_set_min_mode_sends_correct_command(self):
        self._run_control("set_min_mode", CMD_MIN)

    def test_toggle_hold_sends_correct_command(self):
        self._run_control("toggle_hold", CMD_HOLD)

    def test_cancel_max_min_sends_cmd_min_twice(self):
        async def _run():
            mock = _mock_ble_client()
            client = _make_connected_client(mock)
            await client.cancel_max_min()
            assert mock.write_gatt_char.call_count == 2
            for c in mock.write_gatt_char.call_args_list:
                assert c == call(DATA_IN_UUID, CMD_MIN, response=False)

        asyncio.run(_run())

    def test_control_raises_when_not_connected(self):
        async def _run():
            client = UT353BTClient()
            with pytest.raises(RuntimeError):
                await client.set_slow()

        asyncio.run(_run())


# ── connect / disconnect ──────────────────────────────────────────────────────

class TestConnectDisconnect:

    def test_connect_raises_if_device_not_found(self):
        async def _run():
            with patch("ut353bt.client.BleakScanner") as mock_scanner:
                mock_scanner.discover = AsyncMock(return_value=[])
                client = UT353BTClient()
                with pytest.raises(RuntimeError, match="not found"):
                    await client.connect()

        asyncio.run(_run())

    def test_disconnect_is_safe_when_not_connected(self):
        async def _run():
            client = UT353BTClient()
            await client.disconnect()  # should not raise

        asyncio.run(_run())

    def test_async_context_manager_connects_and_disconnects(self):
        async def _run():
            fake_device = MagicMock()
            fake_device.name = "UT353BT"

            with patch("ut353bt.client.BleakScanner") as mock_scanner, \
                 patch("ut353bt.client.BleakClient") as mock_client_class:

                mock_scanner.discover = AsyncMock(return_value=[fake_device])
                mock_instance = _mock_ble_client()
                mock_client_class.return_value = mock_instance

                async with UT353BTClient() as client:
                    assert client.is_connected

                mock_instance.disconnect.assert_called_once()

        asyncio.run(_run())
