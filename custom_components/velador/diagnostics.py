"""Diagnostics de Velador: la tabla de vigilancia completa en un JSON.

Un issue de GitHub con diagnóstico descargable en vez de ping-pong de logs.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    coordinator = entry.runtime_data
    return {
        "options": dict(entry.options),
        "snapshot": coordinator.audit_snapshot(),
        "watch_state": coordinator._dump_state(),  # noqa: SLF001 — mismo paquete
    }
