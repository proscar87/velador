"""Velador — vigila y revive integraciones zombie de Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import VeladorCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

# runtime_data lleva el VeladorCoordinator
VeladorConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: VeladorConfigEntry) -> bool:
    coordinator = VeladorCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: VeladorConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VeladorConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
