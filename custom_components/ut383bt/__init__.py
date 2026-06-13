"""Uni-T UT383BT Lux Meter — Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import UT383BTCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UT383BT from a config entry."""
    coordinator = UT383BTCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-apply options when the user changes them via the Options Flow.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Kick off the first poll immediately (non-blocking) so sensors populate
    # as soon as the device connects, without blocking HA startup.
    hass.async_create_task(coordinator.async_refresh())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: UT383BTCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update (e.g. poll interval change)."""
    coordinator: UT383BTCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.apply_options()
    # Trigger an immediate refresh so the new interval takes effect at once
    # rather than waiting for the remainder of the old timer to expire.
    await coordinator.async_request_refresh()
