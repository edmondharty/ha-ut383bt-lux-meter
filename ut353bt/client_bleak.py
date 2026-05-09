"""Async BLE client for the Uni-T UT353BT sound level meter."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Callable, Optional

from bleak import BleakClient, BleakScanner

from .protocol import (
    CMD_FAST, CMD_HOLD, CMD_MAX, CMD_MIN, CMD_QUERY, CMD_SLOW,
    SoundReading, parse_packet,
)

# BLE GATT characteristic UUIDs (service 0000ff12-...)
DATA_IN_UUID  = "0000ff01-0000-1000-8000-00805f9b34fb"  # Write-without-response
DATA_OUT_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"  # Notify

ReadingCallback = Callable[[SoundReading], None]


class UT353BTClient:
    """Async BLE client for the Uni-T UT353BT sound level meter.

    Supports one-shot polling, continuous streaming, and remote control of
    response speed, Max/Min hold, and freeze hold.

    Examples
    --------
    One-shot poll::

        async with UT353BTClient() as meter:
            reading = await meter.poll()
            print(reading)

    Streaming (async generator)::

        async with UT353BTClient() as meter:
            async for reading in meter.stream(interval=1.0, count=10):
                print(reading)

    Explicit connect/disconnect::

        meter = UT353BTClient()
        await meter.connect()
        try:
            await meter.set_slow()
            reading = await meter.poll()
        finally:
            await meter.disconnect()
    """

    def __init__(
        self,
        device_name: str = "UT353BT",
        scan_timeout: float = 10.0,
        poll_timeout: float = 5.0,
    ) -> None:
        self._device_name  = device_name
        self._scan_timeout = scan_timeout
        self._poll_timeout = poll_timeout

        self._client: Optional[BleakClient]          = None
        self._reading_queue: asyncio.Queue[SoundReading] = asyncio.Queue()

    # ── Connection lifecycle ───────────────────────────────────────────────────

    async def connect(self) -> None:
        """Scan for the device and connect, registering for notifications."""
        devices = await BleakScanner.discover(timeout=self._scan_timeout)
        device  = next(
            (d for d in devices if d.name and self._device_name in d.name),
            None,
        )
        if device is None:
            raise RuntimeError(
                f"'{self._device_name}' not found. "
                "Make sure the meter is powered on with Bluetooth enabled."
            )
        self._client = BleakClient(device)
        await self._client.connect()
        await self._client.start_notify(DATA_OUT_UUID, self._on_notification)
        # Give CoreBluetooth a moment to fully activate the notification
        # subscription before the first poll is sent.
        await asyncio.sleep(0.5)

    async def disconnect(self) -> None:
        """Stop notifications and disconnect from the device."""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(DATA_OUT_UUID)
            except Exception:
                pass
            await self._client.disconnect()
        self._client = None

    async def __aenter__(self) -> "UT353BTClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        """True when a BLE connection is active."""
        return self._client is not None and self._client.is_connected

    # ── Notification handler ───────────────────────────────────────────────────

    def _on_notification(self, sender: object, data: bytearray) -> None:
        """Called by bleak whenever the device sends a notification."""
        reading = parse_packet(data)
        if reading is not None:
            self._reading_queue.put_nowait(reading)

    # ── Reading ────────────────────────────────────────────────────────────────

    async def poll(self, timeout: Optional[float] = None) -> SoundReading:
        """Send one query command and return the next measurement reading.

        Raises
        ------
        RuntimeError
            If not connected.
        asyncio.TimeoutError
            If no response arrives within *timeout* seconds
            (defaults to ``poll_timeout`` set at construction time).
        """
        self._assert_connected()
        effective_timeout = timeout if timeout is not None else self._poll_timeout

        # Drain any stale queued readings before sending a fresh query.
        while not self._reading_queue.empty():
            self._reading_queue.get_nowait()

        await self._client.write_gatt_char(DATA_IN_UUID, CMD_QUERY, response=False)  # type: ignore[union-attr]

        # Poll the queue with short sleep steps instead of wait_for(queue.get()).
        # This yields control back to the event loop on every iteration so that
        # the notification callback (which calls put_nowait) can actually run —
        # particularly important in Jupyter's native-async kernel environment.
        deadline = asyncio.get_event_loop().time() + effective_timeout
        while asyncio.get_event_loop().time() < deadline:
            if not self._reading_queue.empty():
                return self._reading_queue.get_nowait()
            await asyncio.sleep(0.05)
        raise asyncio.TimeoutError()

    async def stream(
        self,
        interval: float = 1.0,
        count: Optional[int] = None,
    ) -> AsyncIterator[SoundReading]:
        """Async generator that polls and yields SoundReading objects.

        Parameters
        ----------
        interval:
            Approximate seconds between successive polls.
        count:
            Total number of readings to yield.  ``None`` streams indefinitely
            until the caller breaks or cancels.
        """
        self._assert_connected()
        yielded = 0
        try:
            while count is None or yielded < count:
                reading = await self.poll()
                yield reading
                yielded += 1
                if count is None or yielded < count:
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    # ── Controls ───────────────────────────────────────────────────────────────

    async def set_slow(self) -> None:
        """Switch the meter to Slow response mode (~1 s time-constant)."""
        await self._send_control(CMD_SLOW)

    async def set_fast(self) -> None:
        """Switch the meter to Fast response mode (~125 ms time-constant)."""
        await self._send_control(CMD_FAST)

    async def set_max_mode(self) -> None:
        """Activate Max-hold mode (Normal → Max).

        The display and reported value will track the highest reading seen.
        """
        await self._send_control(CMD_MAX)

    async def set_min_mode(self) -> None:
        """Advance to Min-hold mode (Max → Min, or Min → Normal).

        Call once when in Max mode to enter Min mode.
        Call again when in Min mode to return to Normal live mode.
        """
        await self._send_control(CMD_MIN)

    async def cancel_max_min(self) -> None:
        """Return to Normal mode from either Max or Min hold.

        Sends CMD_MIN twice to ensure we always land on Normal regardless of
        the current state (Max → Min → Normal).
        """
        await self._send_control(CMD_MIN)
        await asyncio.sleep(0.1)
        await self._send_control(CMD_MIN)

    async def toggle_hold(self) -> None:
        """Toggle the freeze-hold state (live → frozen, or frozen → live)."""
        await self._send_control(CMD_HOLD)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _assert_connected(self) -> None:
        if not self.is_connected:
            raise RuntimeError(
                "Not connected.  Call connect() first or use 'async with'."
            )

    async def _send_control(self, cmd: bytes, settle: float = 0.3) -> None:
        """Write a control command and pause briefly for the ACK to clear."""
        self._assert_connected()
        await self._client.write_gatt_char(DATA_IN_UUID, cmd, response=False)  # type: ignore[union-attr]
        await asyncio.sleep(settle)
