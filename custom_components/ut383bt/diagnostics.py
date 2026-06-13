"""Diagnostics support for the Uni-T UT383BT integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN

_REDACT = {"address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    from .coordinator import UT383BTCoordinator

    coordinator: UT383BTCoordinator = hass.data[DOMAIN][entry.entry_id]
    client = coordinator._client

    last_reading = coordinator.data
    reading_dict: dict[str, Any] | None = None
    if last_reading is not None:
        reading_dict = {
            "illuminance": last_reading.illuminance,
            "unit":        last_reading.unit,
            "status_word": f"0x{last_reading.status_word:08x}",
        }

    data: dict[str, Any] = {
        "address":            entry.unique_id,
        "connection_status":  client.connection_status if client is not None else "Disconnected",
        "last_seen_at":       client.last_seen_at.isoformat() if (client is not None and client.last_seen_at is not None) else None,
        "rssi":               coordinator.get_rssi(),
        "ble_in_registry":    coordinator._get_ble_device() is not None,
        "poll_interval_sec":  entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        "last_reading":       reading_dict,
    }

    return async_redact_data(data, _REDACT)
