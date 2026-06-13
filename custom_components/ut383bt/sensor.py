"""Illuminance and diagnostic sensors for the Uni-T UT383BT."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import LIGHT_LUX, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONN_STATUS_CONNECTED,
    CONN_STATUS_CONNECTING,
    CONN_STATUS_DISCONNECTED,
    DOMAIN,
    SUFFIX_CONNECTION_STATUS,
    SUFFIX_ILLUMINANCE,
    SUFFIX_LAST_SEEN,
    SUFFIX_RSSI,
    SUFFIX_SERIAL,
)
from .coordinator import UT383BTCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UT383BTCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        IlluminanceSensor(coordinator, entry),
        SerialNumberSensor(coordinator, entry),
        ConnectionStatusSensor(coordinator, entry),
        RSSISensor(coordinator, entry),
        LastSeenSensor(coordinator, entry),
    ])


class IlluminanceSensor(CoordinatorEntity[UT383BTCoordinator], SensorEntity):
    """Current illuminance in lux."""

    _attr_device_class  = SensorDeviceClass.ILLUMINANCE
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_suggested_display_precision = 0   # the meter reports whole-lux values
    _attr_has_entity_name = True
    _attr_name = "Illuminance"

    def __init__(self, coordinator: UT383BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{SUFFIX_ILLUMINANCE}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},  # type: ignore[arg-type]
            connections={(CONNECTION_BLUETOOTH, entry.unique_id)},  # type: ignore[arg-type]
            name=entry.title,
            manufacturer="Uni-T (Uni Trend)",
            model="UT383BT",
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.illuminance


class SerialNumberSensor(CoordinatorEntity[UT383BTCoordinator], SensorEntity):
    """Device serial number, read from the Device Information Service."""

    _attr_has_entity_name = True
    _attr_name            = "Serial Number"
    _attr_icon            = "mdi:barcode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: UT383BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id  = f"{entry.unique_id}_{SUFFIX_SERIAL}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})  # type: ignore[arg-type]

    @property
    def native_value(self) -> str | None:
        if self.coordinator._client is None:
            return None
        return self.coordinator._client.serial_number

    # The serial is read once on connect; report it whenever known, even if a
    # later poll fails and the measurement sensor goes Unavailable.
    @property
    def available(self) -> bool:
        return True


class ConnectionStatusSensor(CoordinatorEntity[UT383BTCoordinator], SensorEntity):
    """BLE connection state: Connected / Connecting / Disconnected."""

    _attr_has_entity_name  = True
    _attr_name             = "Connection Status"
    _attr_icon             = "mdi:bluetooth-connect"
    _attr_entity_category  = EntityCategory.DIAGNOSTIC
    _attr_options          = [CONN_STATUS_CONNECTED, CONN_STATUS_CONNECTING, CONN_STATUS_DISCONNECTED]
    _attr_device_class     = SensorDeviceClass.ENUM

    def __init__(self, coordinator: UT383BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id  = f"{entry.unique_id}_{SUFFIX_CONNECTION_STATUS}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})  # type: ignore[arg-type]

    @property
    def native_value(self) -> str:
        if self.coordinator._client is None:
            return CONN_STATUS_DISCONNECTED
        return self.coordinator._client.connection_status

    # Always available — it reports the disconnected state itself.
    @property
    def available(self) -> bool:
        return True


class RSSISensor(CoordinatorEntity[UT383BTCoordinator], SensorEntity):
    """Last known Bluetooth signal strength in dBm."""

    _attr_has_entity_name  = True
    _attr_name             = "Signal Strength"
    _attr_icon             = "mdi:signal"
    _attr_entity_category  = EntityCategory.DIAGNOSTIC
    _attr_device_class     = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class      = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: UT383BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id  = f"{entry.unique_id}_{SUFFIX_RSSI}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})  # type: ignore[arg-type]

    @property
    def native_value(self) -> int | None:
        return self.coordinator.get_rssi()


class LastSeenSensor(CoordinatorEntity[UT383BTCoordinator], SensorEntity):
    """UTC timestamp of the most recent successful reading."""

    _attr_has_entity_name  = True
    _attr_name             = "Last Seen"
    _attr_icon             = "mdi:clock-check-outline"
    _attr_entity_category  = EntityCategory.DIAGNOSTIC
    _attr_device_class     = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: UT383BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id  = f"{entry.unique_id}_{SUFFIX_LAST_SEEN}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})  # type: ignore[arg-type]

    @property
    def native_value(self) -> datetime | None:
        if self.coordinator._client is None:
            return None
        return self.coordinator._client.last_seen_at

    @property
    def available(self) -> bool:
        return True
