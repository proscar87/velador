"""Repairs de Velador: el incurable trae botón "Revivir ahora".

La mitad de la promesa "señal = Repairs" que faltaba: ya reconectaste la
impresora → Arreglar, sin ir a Devices & Services.
"""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .coordinator import VeladorCoordinator


class ReviveFlow(RepairsFlow):
    """Confirmar → resetear strikes/cooldowns y recargar el entry."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                coordinator = getattr(entry, "runtime_data", None)
                if isinstance(coordinator, VeladorCoordinator):
                    await coordinator.async_service_heal(self._entry_id)
                    break
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="confirm")


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None
) -> RepairsFlow:
    return ReviveFlow(issue_id.removeprefix("zombie_"))
