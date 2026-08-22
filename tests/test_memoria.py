"""Que la memoria persistida no se pierda ni se escriba de más.

Dos bugs encontrados leyendo `coordinator.py` línea por línea, ninguno
reportado en producción todavía:

- Un entry a mitad de reload podía perder su WatchState completo (strikes,
  incurable, flapping) porque el escaneo lo marcaba "visto" DESPUÉS del
  `continue` por pocas entidades, no antes.
- El dirty-check de `_save_state` incluía `cadence.last`, que cambia en casi
  cada escaneo con `auto_stale` activo — así que nunca frenaba nada, justo
  lo que el comentario "no moler la flash" dice que debe evitar.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.velador.const import DOMAIN
from custom_components.velador.coordinator import WatchState


async def test_watch_state_sobrevive_una_caida_transitoria_de_entidades(
    hass: HomeAssistant, opciones: dict, integracion
) -> None:
    """_maybe_heal dispara el reload sin esperarlo (a propósito, para no

    bloquear el escaneo). Mientras el entry está a medio recargar, sus
    entidades pueden leer `None` un instante. Si un escaneo cae justo ahí,
    el entry no debe tratarse como "ya no existe".
    """
    entry = MockConfigEntry(domain=DOMAIN, title="Velador", options=opciones)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    otro, ids = await integracion(n=5)
    watch = coordinator._watch.setdefault(otro.entry_id, WatchState())
    watch.reload_attempts = 2
    watch.incurable = True

    # Simula el instante a medio reload: las entidades no responden todavía.
    for entity_id in ids:
        hass.states.async_remove(entity_id)
    await hass.async_block_till_done()

    await coordinator.async_request_refresh()
    await hass.async_block_till_done()

    assert otro.entry_id in coordinator._watch, "se borró la memoria del entry"
    assert coordinator._watch[otro.entry_id].incurable is True
    assert coordinator._watch[otro.entry_id].reload_attempts == 2

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_dirty_check_ignora_el_last_de_la_cadencia(
    hass: HomeAssistant, velador
) -> None:
    """Un cambio solo en `cadence.last` no debe disparar una escritura."""
    coordinator = velador.runtime_data
    coordinator._cadence["sensor.prueba"] = {
        "gaps": [300, 300, 300, 300, 300],
        "last": "2026-01-01T00:00:00+00:00",
        "median": 300,
    }
    coordinator._save_state()  # primer guardado: establece la base

    with patch.object(coordinator._store, "async_delay_save") as guardar:
        coordinator._cadence["sensor.prueba"]["last"] = "2026-01-01T00:05:00+00:00"
        coordinator._save_state()
        assert not guardar.called

    # Un cambio real (la mediana) sí debe seguir disparando la escritura.
    with patch.object(coordinator._store, "async_delay_save") as guardar:
        coordinator._cadence["sensor.prueba"]["median"] = 600
        coordinator._save_state()
        assert guardar.called
