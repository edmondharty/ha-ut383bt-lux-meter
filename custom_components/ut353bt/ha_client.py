"""HA-native BLE client for the Uni-T UT353BT sound level meter.

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
)
from .protocol import (
    CMD_FAST,
    CMD_HOLD,
    CMD_MAX,
    CMD_MIN,
    CMD_QUERY,
    CMD_SLOW,
    Mode,
    SoundReading,
    Speed,
    parse_packet,
)

_LOGGER = logging.getLogger(__name__)


class DeviceNotAvailableError(Exception):
    """Raised when the device is not in HA's Bluetooth registry.

    This is expected while the device is off or out of range — callers
    should treat it as a transient condition and retry on the next poll.
    """


class UT353BTHAClient:
    """Keep-alive BLE client for the UT353BT that uses HA's Bluetooth stack.

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
        self._queue: asyncio.Queue[SoundReading] = asyncio.Queue()
        self._last_reading: Optional[SoundReading] = None
        self._last_seen_at: Optional[datetime] = None

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
        # Give the stack a moment to activate the subscription before the
        # first poll command is sent.
        await asyncio.sleep(0.3)
        _LOGGER.debug("Connected and subscribed to notifications")

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
        _LOGGER.warning("UT353BT disconnected unexpectedly — coordinator will reconnect on next poll")
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

    # ── Notification handler ───────────────────────────────────────────────────

    def _on_notification(self, sender: object, data: bytearray) -> None:
        reading = parse_packet(data)
        if reading is not None:
            self._queue.put_nowait(reading)

    # ── Polling ────────────────────────────────────────────────────────────────

    async def poll(self) -> SoundReading:
        """Request one measurement and return it.

        Reconnects automatically if the connection was dropped since the last
        poll.  On first connection the UT353BT device requires a "wake-up"
        CMD_QUERY before it starts streaming — if the first attempt times out
        the method disconnects, reconnects, and retries once before raising.
        """
        if not self.is_connected:
            down_for = time.monotonic() - getattr(self, '_disconnect_time', time.monotonic())
            _LOGGER.debug("Not connected (down for %.1fs) — reconnecting", down_for)
            await self.connect()

        _t = time.monotonic()
        reading = await self._query_once()
        if reading is not None:
            _LOGGER.debug("poll() success in %.2fs", time.monotonic() - _t)
            return reading

        # First query timed out — the device needs a reconnect to start streaming.
        _LOGGER.debug("First CMD_QUERY timed out after %.2fs — reconnecting and retrying once", time.monotonic() - _t)
        await self.disconnect()
        await asyncio.sleep(0.5)
        await self.connect()

        reading = await self._query_once()
        if reading is not None:
            _LOGGER.debug("poll() success after wake-up retry in %.2fs total", time.monotonic() - _t)
            return reading

        _LOGGER.warning("poll() failed after two attempts (%.2fs total)", time.monotonic() - _t)
        raise asyncio.TimeoutError("No response from UT353BT within timeout")

    async def _query_once(self) -> Optional[SoundReading]:
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

    # ── Controls ───────────────────────────────────────────────────────────────

    async def _send_control(self, cmd: bytes) -> None:
        """Write a control command (write-without-response)."""
        if not self.is_connected:
            await self.connect()
        assert self._client is not None
        await self._client.write_gatt_char(DATA_IN_UUID, cmd, response=False)

    async def set_speed(self, speed: Speed) -> None:
        """Set response speed to Fast or Slow."""
        cmd = CMD_FAST if speed == Speed.FAST else CMD_SLOW
        await self._send_control(cmd)
        await asyncio.sleep(0.15)  # let the device commit the state change
        _LOGGER.debug("Speed set to %s", speed.value)

    async def set_mode(self, target: Mode) -> None:
        """Set measurement mode (Normal / Max / Min).

        The device only supports two commands for mode change:
          - ``CMD_MAX`` transitions Normal → Max.
          - ``CMD_MIN`` advances Max → Min, or Min → Normal.

        This method computes the minimal command sequence from the last known
        mode to reach ``target``.
        """
        current = self._last_reading.mode if self._last_reading else Mode.UNKNOWN

        if current == target:
            return

        # Normalise unknown: assume we are in Normal so we can plan from there.
        if current == Mode.UNKNOWN:
            current = Mode.NORMAL

        # Transition table from current → target
        transitions: dict[tuple[Mode, Mode], list[bytes]] = {
            (Mode.NORMAL, Mode.MAX):    [CMD_MAX],
            (Mode.NORMAL, Mode.MIN):    [CMD_MAX, CMD_MIN],
            (Mode.MAX,    Mode.MIN):    [CMD_MIN],
            (Mode.MAX,    Mode.NORMAL): [CMD_MIN, CMD_MIN],
            (Mode.MIN,    Mode.NORMAL): [CMD_MIN],
            (Mode.MIN,    Mode.MAX):    [CMD_MIN, CMD_MAX],
        }
        cmds = transitions.get((current, target))
        if cmds is None:
            _LOGGER.warning("No transition defined from %s to %s", current, target)
            return

        for cmd in cmds:
            await self._send_control(cmd)
            await asyncio.sleep(0.1)  # Give the device time to process each step
        _LOGGER.debug("Mode transitioned %s → %s", current.value, target.value)

    async def set_hold(self, hold: bool) -> None:
        """Enable or disable freeze-hold.

        Sends ``CMD_HOLD`` only when the desired state differs from the last
        known state (avoiding spurious toggles).
        """
        current_hold = self._last_reading.hold if self._last_reading else None
        if current_hold == hold:
            return
        await self._send_control(CMD_HOLD)
        await asyncio.sleep(0.15)  # let the device commit the state change
        _LOGGER.debug("Hold toggled → %s", hold)

    def update_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the underlying BLEDevice reference.

        HA may provide a refreshed ``BLEDevice`` (e.g. with a better proxy)
        at any time; the coordinator calls this before each poll.
        """
        self._ble_device = ble_device
