"""Hold (freeze) switch entity for the Uni-T UT353BT."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUFFIX_HOLD
from .coordinator import UT353BTCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UT353BTCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HoldSwitch(coordinator, entry)])


class HoldSwitch(CoordinatorEntity[UT353BTCoordinator], SwitchEntity):
    """Switch to freeze (hold) the current reading on the meter display."""

    _attr_has_entity_name = True
    _attr_name            = "Hold"
    _attr_icon            = "mdi:pause-circle-outline"

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{SUFFIX_HOLD}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},  # type: ignore[arg-type]
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.hold

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.client.set_hold(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.client.set_hold(False)
        await self.coordinator.async_request_refresh()
