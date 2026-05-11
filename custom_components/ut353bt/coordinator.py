"""Data update coordinator for the Uni-T UT353BT integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DEFAULT_POLL_TIMEOUT, DOMAIN
from .ha_client import DeviceNotAvailableError, UT353BTHAClient
from .protocol import SoundReading

_LOGGER = logging.getLogger(__name__)


class UT353BTCoordinator(DataUpdateCoordinator[SoundReading]):
    """Coordinator that polls the meter on a configurable interval.

    Keeps the BLE connection alive between polls and reconnects automatically
    on disconnection.  The ``client`` property exposes the underlying
    ``UT353BTHAClient`` so that entities can issue control commands.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry      = entry
        self._address    = entry.unique_id  # MAC address stored as unique_id
        self._client: Optional[UT353BTHAClient] = None

        interval = timedelta(seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Create the BLE client.  Connection is deferred to the first poll.

        The device may not be in the Bluetooth registry yet at startup (HA
        scans passively and populates the registry when it sees an advertisement).
        We create the client with whatever we have — connect() always refreshes
        the BLEDevice via ble_device_callback before connecting.
        """
        from bleak.backends.device import BLEDevice
        ble_device = self._get_ble_device() or BLEDevice(self._address, "UT353BT", {})
        self._client = UT353BTHAClient(
            ble_device,
            poll_timeout=DEFAULT_POLL_TIMEOUT,
            ble_device_callback=self._get_ble_device,
            on_status_changed=self.async_update_listeners,
        )

    async def async_shutdown(self) -> None:
        """Disconnect and clean up."""
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
        # Cancel any scheduled refresh timers in the base coordinator.
        await super().async_shutdown()

    # ── DataUpdateCoordinator interface ────────────────────────────────────────

    async def _async_update_data(self) -> SoundReading:
        """Poll the meter for the latest reading."""
        if self._client is None:
            raise UpdateFailed("Client not initialised")

        # Refresh the BLEDevice reference so establish_connection can use the
        # best available proxy.  If the device is temporarily absent from the
        # registry (e.g. right after an unexpected disconnect while HA re-scans),
        # skip the update but don't fail — poll() will reconnect with the stored
        # device reference.
        ble_device = self._get_ble_device()
        if ble_device is not None:
            self._client.update_ble_device(ble_device)

        try:
            return await self._client.poll()
        except DeviceNotAvailableError:
            _LOGGER.debug("Device %s not in Bluetooth registry — waiting for advertisement", self._address)
            raise UpdateFailed(f"Device {self._address} not in Bluetooth registry") from None
        except asyncio.TimeoutError as err:
            _LOGGER.warning("Poll timed out — device unreachable, sensors will show Unavailable")
            raise UpdateFailed("Timeout waiting for UT353BT response") from err
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Poll failed: %s (%s)", err, type(err).__name__)
            raise UpdateFailed(f"Error communicating with UT353BT: {err}") from err

    # ── Options-flow hook ──────────────────────────────────────────────────────

    def apply_options(self) -> None:
        """Re-read the poll interval from config entry options (called on options update)."""
        seconds = self._entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        self.update_interval = timedelta(seconds=seconds)
        _LOGGER.debug("Poll interval updated to %s seconds", seconds)
        # Cancel the existing timer and reschedule with the new interval immediately.
        self._schedule_refresh()

    # ── Helpers ────────────────────────────────────────────────────────────────

    @property
    def client(self) -> UT353BTHAClient:
        """The underlying BLE client (used by entities for control commands)."""
        assert self._client is not None, "Client accessed before async_setup()"
        return self._client

    def _get_ble_device(self) -> Optional[BLEDevice]:
        """Look up the current ``BLEDevice`` from the HA Bluetooth registry."""
        assert self._address is not None
        return bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )

    def get_rssi(self) -> Optional[int]:
        """Return the last known RSSI (dBm) for the device, or None."""
        service_info = bluetooth.async_last_service_info(
            self.hass, self._address, connectable=True
        )
        return service_info.rssi if service_info is not None else None
