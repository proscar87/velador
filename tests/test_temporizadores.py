"""Que no queden temporizadores vivos al descargar la entry.

Esto no es higiene: un cambio de opciones recarga la entry, y el temporizador
de confirmación de olas dura 10 minutos. Si sobrevive, al dispararse el
coordinator viejo escribe su copia del historial encima de la que ya lleva el
nuevo. El arnés de HA falla la prueba si algo queda agendado, así que la
guardia real es el arnés; los asserts solo dicen qué se rompió.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.velador.const import DOMAIN


async def test_descargar_cancela_los_temporizadores(
    hass: HomeAssistant, opciones: dict, integracion
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Velador", options=opciones)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    # Una ola candidata agenda el confirmador de 10 minutos...
    _, ids = await integracion(n=100)
    for entity_id in ids[:60]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    assert coordinator._timers, "la ola candidata no agendó nada que probar"

    # ...y descargar tiene que soltarlo.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not coordinator._timers


async def test_recargar_no_deja_al_coordinator_viejo_escribiendo(
    hass: HomeAssistant, opciones: dict, integracion
) -> None:
    """Un cambio de opciones recarga: el de antes no debe seguir agendado."""
    entry = MockConfigEntry(domain=DOMAIN, title="Velador", options=opciones)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    viejo = entry.runtime_data

    _, ids = await integracion(n=100)
    for entity_id in ids[:60]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    assert viejo._timers

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert not viejo._timers
    assert entry.runtime_data is not viejo, "el reload no creó un coordinator nuevo"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
