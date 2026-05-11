"""Tests for the UT353BT config flow.

These tests run entirely without a real Bluetooth device or HA instance by
using the ``hass`` fixture from ``pytest-homeassistant-custom-component`` and
mocking the Bluetooth layer.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ut353bt.const import CONF_POLL_INTERVAL, DOMAIN
from tests.ha.conftest import TEST_ADDRESS, TEST_NAME, flow_ctx


def _make_bluetooth_service_info(address: str, name: str) -> BluetoothServiceInfoBleak:
    info = MagicMock(spec=BluetoothServiceInfoBleak)
    info.address = address
    info.name    = name
    return info


# ---------------------------------------------------------------------------
# Bluetooth auto-discovery flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bluetooth_discovery_confirm(hass):
    """Discovery step followed by user confirmation creates a config entry."""
    discovery = _make_bluetooth_service_info(TEST_ADDRESS, TEST_NAME)

    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "bluetooth"},
            data=discovery,
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    with flow_ctx(hass):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == TEST_NAME
    assert result2["data"]["address"] == TEST_ADDRESS


@pytest.mark.asyncio
async def test_bluetooth_discovery_aborts_if_already_configured(hass):
    """Second discovery for the same MAC is rejected."""
    discovery = _make_bluetooth_service_info(TEST_ADDRESS, TEST_NAME)

    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "bluetooth"}, data=discovery
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})

    with flow_ctx(hass):
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "bluetooth"}, data=discovery
        )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Manual user flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_flow_manual_address(hass):
    """User can configure the integration by typing a MAC address."""
    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with flow_ctx(hass):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"address": TEST_ADDRESS}
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"]["address"] == TEST_ADDRESS


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_options_flow_poll_interval(hass):
    """Options flow allows changing the poll interval."""
    entry = await _create_entry(hass)

    with flow_ctx(hass):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    with flow_ctx(hass):
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_POLL_INTERVAL: 60}
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_POLL_INTERVAL] == 60


async def _create_entry(hass):
    """Helper: create a config entry for tests that need one pre-existing."""
    discovery = _make_bluetooth_service_info(TEST_ADDRESS, TEST_NAME)
    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "bluetooth"}, data=discovery
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]
