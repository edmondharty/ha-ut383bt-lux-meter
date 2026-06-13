"""Config flow for the Uni-T UT383BT integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class UT383BTConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and manual configuration of the UT383BT."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    # ── Bluetooth auto-discovery ───────────────────────────────────────────────

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle discovery via HA's Bluetooth integration."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address,
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to confirm the discovered device."""
        assert self._discovery_info is not None
        info = self._discovery_info

        if user_input is not None:
            return self.async_create_entry(
                title=info.name or info.address,
                data={"address": info.address},
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": info.name or info.address,
                "address": info.address,
            },
        )

    # ── Manual entry (fallback) ────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow the user to enter a Bluetooth address manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input["address"].strip().upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"UT383BT ({address})",
                data={"address": address},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("address"): str,
            }),
            errors=errors,
        )

    # ── Options flow ──────────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "UT383BTOptionsFlow":
        return UT383BTOptionsFlow(config_entry)


class UT383BTOptionsFlow(OptionsFlow):
    """Handle options (poll interval)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_POLL_INTERVAL, default=current): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }),
        )
