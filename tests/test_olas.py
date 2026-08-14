"""Olas sub-umbral: detección, clasificación y lo que llega al panel.

Contra HA de verdad, así que los Repairs se comprueban en el issue registry
real y no en un diccionario inventado por la prueba.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.velador.const import (
    DOMAIN,
    EVENT_WAVE,
    EVENT_WAVE_CHRONIC,
    EVENT_WAVE_RECURRENT,
    WAVE_CHRONIC_PER_DAY,
)


def sembrar(coordinator, entry_id: str, cuantas: int, durante_horas: float) -> None:
    """Historial de olas ya puesto: N repartidas en esas horas, la última ahora."""
    ahora = dt_util.utcnow()
    paso = durante_horas / max(cuantas - 1, 1)
    coordinator._waves[entry_id] = [
        ahora - timedelta(hours=durante_horas - k * paso) for k in range(cuantas)
    ]


def escanear(coordinator):
    from custom_components.velador.coordinator import VeladorData

    data = VeladorData()
    coordinator._scan_waves(data)
    return data


async def test_ola_que_se_recupera_sola_se_cuenta(
    hass: HomeAssistant, velador, integracion, freezer
) -> None:
    """El camino completo: caída masiva, espera, recuperación, ola contada."""
    coordinator = velador.runtime_data
    entry, ids = await integracion(n=100)
    disparados = []
    hass.bus.async_listen(EVENT_WAVE, lambda ev: disparados.append(ev))

    for entity_id in ids[:60]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()

    # Volvieron solas antes de que venciera la confirmación.
    for entity_id in ids[:60]:
        hass.states.async_set(entity_id, "on")
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(coordinator._waves.get(entry.entry_id, [])) == 1
    assert disparados, "no se disparó velador_wave"


async def test_si_no_vuelven_no_es_ola(
    hass: HomeAssistant, velador, integracion, freezer
) -> None:
    """Si siguen muertas nunca fue una ola: es zombie, y de eso hay escalera."""
    coordinator = velador.runtime_data
    entry, ids = await integracion(n=100)

    for entity_id in ids[:95]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert entry.entry_id not in coordinator._waves


async def test_pocas_entidades_no_hacen_ola(
    hass: HomeAssistant, velador, integracion
) -> None:
    """Bajo el mínimo y bajo la mitad del entry: no hay nada que reportar."""
    coordinator = velador.runtime_data
    entry, ids = await integracion(n=100)

    for entity_id in ids[:20]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()

    bucket = coordinator._wave_bucket.get(entry.entry_id)
    assert bucket is None or not bucket["marcada"]


async def test_reincidencia_levanta_un_repair_de_verdad(
    hass: HomeAssistant, velador, integracion
) -> None:
    """Tres olas esporádicas en días distintos: eso sí es un aparato enfermo."""
    coordinator = velador.runtime_data
    entry, _ = await integracion(n=100)
    avisos = []
    hass.bus.async_listen(EVENT_WAVE_RECURRENT, lambda ev: avisos.append(ev))

    sembrar(coordinator, entry.entry_id, cuantas=4, durante_horas=72)
    data = escanear(coordinator)
    await hass.async_block_till_done()

    assert len(data.waves) == 1
    assert not data.waves_chronic
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"waves_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_placeholders["count"] == "4"
    assert avisos


async def test_el_conteo_del_repair_se_refresca(
    hass: HomeAssistant, velador, integracion
) -> None:
    """El bug que se vio en producción: decía 14 con el sensor en 31."""
    coordinator = velador.runtime_data
    entry, _ = await integracion(n=100)
    sembrar(coordinator, entry.entry_id, cuantas=4, durante_horas=72)
    escanear(coordinator)

    coordinator._waves[entry.entry_id].append(dt_util.utcnow())
    escanear(coordinator)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"waves_{entry.entry_id}")
    assert issue.translation_placeholders["count"] == "5"


async def test_integracion_de_nube_se_archiva_sin_repair(
    hass: HomeAssistant, velador, integracion
) -> None:
    """El caso real: growatt hizo 33 olas en 39 h. No hay cable que revisar."""
    coordinator = velador.runtime_data
    entry, _ = await integracion(dominio="nube_prueba", n=40, titulo="Texcoco (growatt)")
    cronicas = []
    hass.bus.async_listen(EVENT_WAVE_CHRONIC, lambda ev: cronicas.append(ev))

    sembrar(coordinator, entry.entry_id, cuantas=33, durante_horas=39)
    data = escanear(coordinator)
    await hass.async_block_till_done()

    assert not data.waves
    assert len(data.waves_chronic) == 1
    assert data.waves_chronic[0]["por_dia"] >= WAVE_CHRONIC_PER_DAY
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"waves_{entry.entry_id}") is None
    assert cronicas

    # Y no se re-anuncia en cada escaneo.
    cronicas.clear()
    escanear(coordinator)
    await hass.async_block_till_done()
    assert not cronicas


async def test_una_mala_noche_sigue_siendo_repair(
    hass: HomeAssistant, velador, integracion
) -> None:
    """Seis olas de 22:00 a 03:00 son una noche, no un patrón de nube."""
    coordinator = velador.runtime_data
    entry, _ = await integracion(n=100)

    sembrar(coordinator, entry.entry_id, cuantas=6, durante_horas=5)
    data = escanear(coordinator)
    await hass.async_block_till_done()

    assert not data.waves_chronic
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"waves_{entry.entry_id}")


async def test_rozar_el_umbral_no_saca_de_cronica(
    hass: HomeAssistant, velador, integracion, freezer
) -> None:
    """Histéresis: sin margen de salida el Repair parpadea y grita en falso."""
    coordinator = velador.runtime_data
    entry, _ = await integracion(dominio="nube_prueba", n=40, titulo="Nube (tuya)")
    falsos = []
    hass.bus.async_listen(EVENT_WAVE_RECURRENT, lambda ev: falsos.append(ev))

    sembrar(coordinator, entry.entry_id, cuantas=9, durante_horas=48)
    assert len(escanear(coordinator).waves_chronic) == 1

    # Roza el umbral por abajo: sigue archivada.
    coordinator._waves[entry.entry_id] = coordinator._waves[entry.entry_id][:8]
    freezer.tick(timedelta(hours=6))
    data = escanear(coordinator)
    await hass.async_block_till_done()

    assert len(data.waves_chronic) == 1
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"waves_{entry.entry_id}") is None
    assert not falsos, "re-diagnosticó una integración de nube como falla física"

    # Pero si baja de verdad, vuelve a ser aviso normal.
    coordinator._waves[entry.entry_id] = coordinator._waves[entry.entry_id][:4]
    freezer.tick(timedelta(days=2))
    data = escanear(coordinator)
    await hass.async_block_till_done()

    assert not data.waves_chronic
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"waves_{entry.entry_id}")


async def test_la_marca_de_cronica_sobrevive_al_reinicio(
    hass: HomeAssistant, velador, integracion
) -> None:
    """Sin persistirla, cada arranque vuelve a anunciar lo mismo."""
    coordinator = velador.runtime_data
    entry, _ = await integracion(dominio="nube_prueba", n=40, titulo="Starlink")

    sembrar(coordinator, entry.entry_id, cuantas=33, durante_horas=39)
    escanear(coordinator)
    volcado = coordinator._dump_state()

    assert volcado["waves_chronic"] == [entry.entry_id]

    # Un arranque nuevo leyendo ese store no debe re-anunciar.
    coordinator._waves_chronic = set()
    coordinator._waves_chronic = {
        eid for eid in volcado["waves_chronic"] if eid in coordinator._waves
    }
    cronicas = []
    hass.bus.async_listen(EVENT_WAVE_CHRONIC, lambda ev: cronicas.append(ev))
    data = escanear(coordinator)
    await hass.async_block_till_done()

    assert len(data.waves_chronic) == 1
    assert not cronicas
