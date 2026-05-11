"""Battery low binary sensor for the Uni-T UT353BT."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUFFIX_BATTERY
from .coordinator import UT353BTCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UT353BTCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BatteryLowBinarySensor(coordinator, entry)])


class BatteryLowBinarySensor(CoordinatorEntity[UT353BTCoordinator], BinarySensorEntity):
    """True when the meter's battery is low."""

    _attr_device_class    = BinarySensorDeviceClass.BATTERY
    _attr_has_entity_name = True
    _attr_name            = "Battery Low"

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{SUFFIX_BATTERY}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},  # type: ignore[arg-type]
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.low_battery
