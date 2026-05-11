"""Sound level and diagnostic sensors for the Uni-T UT353BT."""
from __future__ import annotations

from datetime import datetime

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfSoundPressure
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONN_STATUS_CONNECTED,
    CONN_STATUS_CONNECTING,
    CONN_STATUS_DISCONNECTED,
    DOMAIN,
    SUFFIX_CONNECTION_STATUS,
    SUFFIX_LAST_SEEN,
    SUFFIX_RSSI,
    SUFFIX_SOUND,
)
from .coordinator import UT353BTCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UT353BTCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SoundLevelSensor(coordinator, entry),
        ConnectionStatusSensor(coordinator, entry),
        RSSISensor(coordinator, entry),
        LastSeenSensor(coordinator, entry),
    ])


class SoundLevelSensor(CoordinatorEntity[UT353BTCoordinator], SensorEntity):
    """Current sound pressure level in dBA."""

    _attr_device_class  = SensorDeviceClass.SOUND_PRESSURE
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfSoundPressure.WEIGHTED_DECIBEL_A
    _attr_has_entity_name = True
    _attr_name = "Sound Level"

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{SUFFIX_SOUND}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},  # type: ignore[arg-type]
            connections={(CONNECTION_BLUETOOTH, entry.unique_id)},  # type: ignore[arg-type]
            name=entry.title,
            manufacturer="Uni-T (Uni Trend)",
            model="UT353BT",
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.sound_dba


class ConnectionStatusSensor(CoordinatorEntity[UT353BTCoordinator], SensorEntity):
    """BLE connection state: Connected / Connecting / Disconnected."""

    _attr_has_entity_name  = True
    _attr_name             = "Connection Status"
    _attr_icon             = "mdi:bluetooth-connect"
    _attr_entity_category  = EntityCategory.DIAGNOSTIC
    _attr_options          = [CONN_STATUS_CONNECTED, CONN_STATUS_CONNECTING, CONN_STATUS_DISCONNECTED]
    _attr_device_class     = SensorDeviceClass.ENUM

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
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


class RSSISensor(CoordinatorEntity[UT353BTCoordinator], SensorEntity):
    """Last known Bluetooth signal strength in dBm."""

    _attr_has_entity_name  = True
    _attr_name             = "Signal Strength"
    _attr_icon             = "mdi:signal"
    _attr_entity_category  = EntityCategory.DIAGNOSTIC
    _attr_device_class     = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class      = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id  = f"{entry.unique_id}_{SUFFIX_RSSI}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})  # type: ignore[arg-type]

    @property
    def native_value(self) -> int | None:
        return self.coordinator.get_rssi()


class LastSeenSensor(CoordinatorEntity[UT353BTCoordinator], SensorEntity):
    """UTC timestamp of the most recent successful reading."""

    _attr_has_entity_name  = True
    _attr_name             = "Last Seen"
    _attr_icon             = "mdi:clock-check-outline"
    _attr_entity_category  = EntityCategory.DIAGNOSTIC
    _attr_device_class     = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
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
