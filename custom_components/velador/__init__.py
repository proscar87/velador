"""Velador — vigila y revive integraciones zombie de Home Assistant."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import DOMAIN
from .coordinator import VeladorCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

# runtime_data lleva el VeladorCoordinator
VeladorConfigEntry = ConfigEntry

SERVICE_HEAL_SCHEMA = vol.Schema({vol.Optional("entry_id"): str})


def _coordinator(hass: HomeAssistant) -> VeladorCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if isinstance(coordinator, VeladorCoordinator):
            return coordinator
    return None


async def async_setup_entry(hass: HomeAssistant, entry: VeladorConfigEntry) -> bool:
    coordinator = VeladorCoordinator(hass, entry)
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_start())
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _register_services(hass)
    return True


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "heal"):
        return

    async def _heal(call: ServiceCall) -> dict:
        coordinator = _coordinator(hass)
        if coordinator is None:
            return {"healed": []}
        return await coordinator.async_service_heal(call.data.get("entry_id"))

    async def _audit(call: ServiceCall) -> dict:
        coordinator = _coordinator(hass)
        if coordinator is None:
            return {}
        return coordinator.audit_snapshot()

    hass.services.async_register(
        DOMAIN,
        "heal",
        _heal,
        schema=SERVICE_HEAL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "audit",
        _audit,
        supports_response=SupportsResponse.ONLY,
    )


async def _async_update_listener(hass: HomeAssistant, entry: VeladorConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VeladorConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not hass.config_entries.async_loaded_entries(DOMAIN):
        hass.services.async_remove(DOMAIN, "heal")
        hass.services.async_remove(DOMAIN, "audit")
    return unloaded
