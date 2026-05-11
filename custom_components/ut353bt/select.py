"""Mode and Speed select entities for the Uni-T UT353BT."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUFFIX_MODE, SUFFIX_SPEED
from .coordinator import UT353BTCoordinator
from .protocol import Mode, Speed

_LOGGER = logging.getLogger(__name__)

_MODE_OPTIONS  = [Mode.NORMAL.value, Mode.MAX.value, Mode.MIN.value]
_SPEED_OPTIONS = [Speed.FAST.value, Speed.SLOW.value]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UT353BTCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ModeSelect(coordinator, entry),
        SpeedSelect(coordinator, entry),
    ])


class ModeSelect(CoordinatorEntity[UT353BTCoordinator], SelectEntity):
    """Select entity to control Normal / Max / Min measurement mode."""

    _attr_options         = _MODE_OPTIONS
    _attr_has_entity_name = True
    _attr_name            = "Mode"
    _attr_icon            = "mdi:chart-line"

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{SUFFIX_MODE}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},  # type: ignore[arg-type]
        )

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        mode = self.coordinator.data.mode
        return mode.value if mode != Mode.UNKNOWN else None

    async def async_select_option(self, option: str) -> None:
        target = Mode(option)
        await self.coordinator.client.set_mode(target)
        await self.coordinator.async_request_refresh()


class SpeedSelect(CoordinatorEntity[UT353BTCoordinator], SelectEntity):
    """Select entity to control Fast / Slow response speed."""

    _attr_options         = _SPEED_OPTIONS
    _attr_has_entity_name = True
    _attr_name            = "Response Speed"
    _attr_icon            = "mdi:speedometer"

    def __init__(self, coordinator: UT353BTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{SUFFIX_SPEED}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},  # type: ignore[arg-type]
        )

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        speed = self.coordinator.data.speed
        return speed.value if speed != Speed.UNKNOWN else None

    async def async_select_option(self, option: str) -> None:
        target = Speed(option)
        await self.coordinator.client.set_speed(target)
        await self.coordinator.async_request_refresh()
