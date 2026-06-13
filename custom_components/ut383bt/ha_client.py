"""HA-native BLE client for the Uni-T UT383BT lux meter.

Uses Home Assistant's Bluetooth integration APIs so that both the built-in
Bluetooth adapter and ESPHome Bluetooth proxies are transparently supported.
No BLE scanning is performed here — HA discovers the device and hands us a
``BLEDevice`` object obtained from the HA Bluetooth registry.

Connection is kept alive and re-established automatically on disconnect using
``bleak_retry_connector``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError, BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from .const import (
    CONN_STATUS_CONNECTED,
    CONN_STATUS_CONNECTING,
    CONN_STATUS_DISCONNECTED,
    DATA_IN_UUID,
    DATA_OUT_UUID,
    DEFAULT_POLL_TIMEOUT,
    SERIAL_NUMBER_UUID,
)
from .protocol import CMD_QUERY, LuxReading, parse_packet

_LOGGER = logging.getLogger(__name__)


class DeviceNotAvailableError(Exception):
    """Raised when the device is not in HA's Bluetooth registry.

    This is expected while the device is off or out of range — callers
    should treat it as a transient condition and retry on the next poll.
    """


class UT383BTHAClient:
    """Keep-alive BLE client for the UT383BT that uses HA's Bluetooth stack.

    Parameters
    ----------
    ble_device:
        The ``BLEDevice`` obtained from HA's Bluetooth registry
        (passed by the coordinator or config flow).
    poll_timeout:
        Seconds to wait for a notification response to a query command.
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
        ble_device_callback: Callable[[], Optional[BLEDevice]] | None = None,
        on_status_changed: Callable[[], None] | None = None,
    ) -> None:
        self._ble_device   = ble_device
        self._poll_timeout = poll_timeout
        self._ble_device_callback = ble_device_callback
        self._on_status_changed = on_status_changed

        self._client: Optional[BleakClient] = None
        self._connecting: bool = False
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._queue: asyncio.Queue[LuxReading] = asyncio.Queue()
        self._last_reading: Optional[LuxReading] = None
        self._last_seen_at: Optional[datetime] = None
        self._serial_number: Optional[str] = None

    # ── Connection ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish a BLE connection via HA's Bluetooth stack.

        Uses ``bleak_retry_connector.establish_connection`` so that:
        - ESPHome Bluetooth proxies are automatically selected.
        - Transient GATT errors are retried with exponential back-off.
        """
        # Refuse to connect if the device hasn't been seen by HA's BT scanner
        # yet — establish_connection would immediately fail with "no available
        # connection slot" and waste a BlueZ slot for nothing.
        if self._ble_device_callback is not None:
            fresh = self._ble_device_callback()
            if fresh is None:
                raise DeviceNotAvailableError(
                    f"Device {self._ble_device.address} not in Bluetooth registry — "
                    "waiting for advertisement"
                )
            self._ble_device = fresh

        if self._connect_lock.locked():
            raise RuntimeError("Connection attempt already in progress")

        async with self._connect_lock:

            _LOGGER.debug("Connecting to %s (%s)", self._ble_device.name, self._ble_device.address)
            _t = time.monotonic()
            self._connecting = True
            self._notify_status_changed()
            try:
                self._client = await asyncio.wait_for(
                    establish_connection(
                        BleakClientWithServiceCache,
                        self._ble_device,
                        self._ble_device.name or self._ble_device.address,
                        self._on_disconnect,
                        max_attempts=1,
                    ),
                    timeout=30.0,
                )
            finally:
                self._connecting = False
                self._notify_status_changed()
            _LOGGER.debug("establish_connection took %.2fs", time.monotonic() - _t)
        # Give BlueZ time to fully publish GATT characteristic objects on DBus
        # before calling start_notify — avoids AcquireNotify failures on startup.
        await asyncio.sleep(0.5)
        # Clear any stale notification subscription left by a previous session.
        # If BlueZ still has the characteristic in "Notify acquired" state, the
        # start_notify call below would raise BleakDBusError.NotPermitted.
        try:
            await self._client.stop_notify(DATA_OUT_UUID)
            await asyncio.sleep(0.1)
        except Exception:  # noqa: BLE001
            pass
        await self._client.start_notify(DATA_OUT_UUID, self._on_notification)
        # Read the serial number once (Device Information Service, 0x2a25).
        # Cached so we only hit the GATT characteristic on the first connect.
        await self._read_serial_number()
        # Give the stack a moment to activate the subscription before the
        # first poll command is sent.
        await asyncio.sleep(0.3)
        _LOGGER.debug("Connected and subscribed to notifications")

    async def _read_serial_number(self) -> None:
        """Read and cache the DIS serial number, if not already known.

        Best-effort: any failure (characteristic absent, read not permitted, or
        transient GATT error) is swallowed and leaves the serial as None so it
        can be retried on the next connect.
        """
        if self._serial_number is not None or self._client is None:
            return
        try:
            raw = await self._client.read_gatt_char(SERIAL_NUMBER_UUID)
            serial = bytes(raw).decode("ascii", errors="replace").strip("\x00").strip()
            if serial:
                self._serial_number = serial
                _LOGGER.debug("Read serial number: %s", serial)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not read serial number characteristic: %s", err)

    async def disconnect(self) -> None:
        """Gracefully stop notifications and disconnect."""
        if self._client is not None:
            try:
                if self._client.is_connected:
                    await self._client.stop_notify(DATA_OUT_UUID)
            except Exception:  # noqa: BLE001
                pass
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        _LOGGER.debug("Disconnected")

    def _on_disconnect(self, client: BleakClient) -> None:
        """Called by bleak when the device disconnects unexpectedly."""
        if self._connecting:
            # Fired by establish_connection's internal retry logic — not a real
            # unexpected disconnect.  establish_connection will handle the retry.
            _LOGGER.debug("Disconnect during connect phase — establish_connection will retry")
            return
        self._disconnect_time = time.monotonic()
        _LOGGER.warning("UT383BT disconnected unexpectedly — coordinator will reconnect on next poll")
        self._client = None
        self._notify_status_changed()

    def _notify_status_changed(self) -> None:
        """Fire the status-changed callback, swallowing any exception."""
        if self._on_status_changed is not None:
            try:
                self._on_status_changed()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Exception in on_status_changed callback", exc_info=True)

    @property
    def is_connected(self) -> bool:
        """True when an active BLE connection exists."""
        return self._client is not None and self._client.is_connected

    @property
    def connection_status(self) -> str:
        """Human-readable connection state for the diagnostic sensor."""
        if self._connecting:
            return CONN_STATUS_CONNECTING
        if self.is_connected:
            return CONN_STATUS_CONNECTED
        return CONN_STATUS_DISCONNECTED

    @property
    def last_seen_at(self) -> Optional[datetime]:
        """UTC datetime of the last successful reading, or None."""
        return self._last_seen_at

    @property
    def serial_number(self) -> Optional[str]:
        """Cached Device-Information-Service serial number, or None if unread."""
        return self._serial_number

    # ── Notification handler ───────────────────────────────────────────────────

    def _on_notification(self, sender: object, data: bytearray) -> None:
        reading = parse_packet(data)
        if reading is not None:
            self._queue.put_nowait(reading)

    # ── Polling ────────────────────────────────────────────────────────────────

    async def poll(self) -> LuxReading:
        """Request one measurement and return it.

        Reconnects automatically if the connection was dropped since the last
        poll.  Handles two reconnect triggers:

        1. BlueZ GATT/DBus error — BlueZ can tear down its internal GATT objects
           and delay firing the disconnect callback by several seconds.  During
           that window ``is_connected`` is still True but any write raises
           ``BleakDBusError`` (UnknownObject).  We treat this as a forced
           disconnect, clean up, and reconnect immediately.

        2. Timeout — on first connection the meter requires a "wake-up"
           CMD_QUERY; if it times out we disconnect, reconnect, and retry.

        After any reconnect we retry the query up to _POST_RECONNECT_ATTEMPTS
        times with a short pause between attempts.  The device is connected but
        can take a moment to start responding after a fresh GATT subscription.
        """
        if not self.is_connected:
            down_for = time.monotonic() - getattr(self, '_disconnect_time', time.monotonic())
            _LOGGER.debug("Not connected (down for %.1fs) — reconnecting", down_for)
            await self.connect()

        _t = time.monotonic()
        try:
            reading = await self._query_once()
        except (BleakDBusError, BleakError) as err:
            _LOGGER.warning(
                "GATT error during poll (%.2fs) — forcing reconnect: %s",
                time.monotonic() - _t, err,
            )
            self._client = None
            self._notify_status_changed()
            await asyncio.sleep(0.5)
            await self.connect()
            reading = await self._query_after_reconnect(_t, "GATT-error")
            if reading is not None:
                return reading
            raise asyncio.TimeoutError("No response from UT383BT within timeout") from err

        if reading is not None:
            _LOGGER.debug("poll() success in %.2fs", time.monotonic() - _t)
            return reading

        # First query timed out — the device needs a reconnect to start streaming.
        _LOGGER.debug("First CMD_QUERY timed out after %.2fs — reconnecting and retrying", time.monotonic() - _t)
        await self.disconnect()
        await asyncio.sleep(0.5)
        await self.connect()

        reading = await self._query_after_reconnect(_t, "wake-up")
        if reading is not None:
            return reading

        _LOGGER.warning("poll() failed after wake-up reconnect (%.2fs total)", time.monotonic() - _t)
        raise asyncio.TimeoutError("No response from UT383BT within timeout")

    # Number of query attempts after a reconnect (with _POST_RECONNECT_PAUSE between each).
    _POST_RECONNECT_ATTEMPTS = 3
    _POST_RECONNECT_PAUSE    = 1.0  # seconds

    async def _query_after_reconnect(self, _t: float, label: str) -> Optional[LuxReading]:
        """Retry _query_once() up to _POST_RECONNECT_ATTEMPTS times after a reconnect.

        The device is connected and subscribed but may take a moment to start
        responding after a fresh GATT subscription.  Returns the first reading
        received, or None if all attempts time out.
        """
        for attempt in range(1, self._POST_RECONNECT_ATTEMPTS + 1):
            reading = await self._query_once()
            if reading is not None:
                _LOGGER.debug(
                    "poll() success after %s reconnect (attempt %d/%d) in %.2fs total",
                    label, attempt, self._POST_RECONNECT_ATTEMPTS, time.monotonic() - _t,
                )
                return reading
            if attempt < self._POST_RECONNECT_ATTEMPTS:
                _LOGGER.debug(
                    "Post-%s query attempt %d/%d timed out — retrying in %.1fs",
                    label, attempt, self._POST_RECONNECT_ATTEMPTS, self._POST_RECONNECT_PAUSE,
                )
                await asyncio.sleep(self._POST_RECONNECT_PAUSE)

        _LOGGER.warning(
            "poll() failed after %s reconnect — all %d attempts timed out (%.2fs total)",
            label, self._POST_RECONNECT_ATTEMPTS, time.monotonic() - _t,
        )
        return None

    async def _query_once(self) -> Optional[LuxReading]:
        """Send CMD_QUERY and wait up to poll_timeout for a notification.

        Returns the reading, or None on timeout (without raising).
        """
        # Drain any stale readings accumulated while HA was idle.
        while not self._queue.empty():
            self._queue.get_nowait()

        assert self._client is not None
        await self._client.write_gatt_char(DATA_IN_UUID, CMD_QUERY, response=False)

        deadline = asyncio.get_event_loop().time() + self._poll_timeout
        while asyncio.get_event_loop().time() < deadline:
            if not self._queue.empty():
                reading = self._queue.get_nowait()
                self._last_reading = reading
                self._last_seen_at = datetime.now(timezone.utc)
                return reading
            await asyncio.sleep(0.05)

        return None

    def update_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the underlying BLEDevice reference.

        HA may provide a refreshed ``BLEDevice`` (e.g. with a better proxy)
        at any time; the coordinator calls this before each poll.
        """
        self._ble_device = ble_device
