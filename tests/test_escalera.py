"""La escalera de curación: cuándo recarga, cuándo se rinde y cuándo da por curado.

Dos bugs encontrados con sondas contra HA de verdad, ninguno reportado en
producción todavía:

- Un incurable declarado por un canario o por un sensor congelado se daba por
  curado en el siguiente escaneo, porque el ratio global del entry estaba sano
  (nunca estuvo enfermo por ratio). `velador_healed` falso, el Repair borrado,
  la escalera desde cero — y a la tercera vuelta, flapping con un Repair de
  "esto es físico" igual de falso.
- `cooldown_hours` no hacía nada: el veredicto de incurable se revisaba antes
  que el backoff, así que el último escalón nunca se esperaba. Misma escalera
  con 1 h que con 48 h.

El reload se sustituye solo para la integración vigilada, que es un módulo de
prueba: lo que se mide es la decisión de Velador, no si el reload cura.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.velador.const import (
    DOMAIN,
    EVENT_HEALED,
    EVENT_INCURABLE,
)


@pytest.fixture
def vigilar(hass: HomeAssistant, integracion, monkeypatch):
    """Monta Velador sobre una integración de 10 entidades y anota sus reloads.

    `opciones` puede ser una función de los entity_ids, para poder nombrar un
    canario o un congelado antes de montar. Devuelve un dict con la entry de
    Velador, la vigilada, sus entidades y las listas de reloads / incurables /
    curadas (en minutos desde el arranque).
    """
    real_reload = hass.config_entries.async_reload

    async def _hacer(opciones, n: int = 10) -> dict:
        otro, ids = await integracion(n=n)
        if callable(opciones):
            opciones = opciones(ids)
        t0 = dt_util.utcnow()
        minutos = lambda: round((dt_util.utcnow() - t0).total_seconds() / 60)  # noqa: E731
        caso = {"otro": otro, "ids": ids, "reloads": [], "incurables": [], "curadas": []}
        hass.bus.async_listen(EVENT_INCURABLE, lambda _e: caso["incurables"].append(minutos()))
        hass.bus.async_listen(EVENT_HEALED, lambda _e: caso["curadas"].append(minutos()))

        async def _reload(entry_id: str) -> bool:
            if entry_id == otro.entry_id:
                caso["reloads"].append(minutos())
                if caso.get("tras_reload"):
                    caso["tras_reload"]()
                return True
            return await real_reload(entry_id)

        monkeypatch.setattr(hass.config_entries, "async_reload", _reload)
        entry = MockConfigEntry(
            domain=DOMAIN, title="Velador", options={"grace_minutes": 0, **opciones}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        caso["entry"] = entry
        return caso

    return _hacer


async def avanzar(hass: HomeAssistant, freezer, minutos: int, cada_paso=None) -> None:
    """Deja correr el reloj en pasos de 5 min (el intervalo de escaneo)."""
    for _ in range(minutos // 5):
        freezer.tick(timedelta(minutes=5))
        if cada_paso:
            cada_paso()
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def bajar(hass: HomeAssistant, freezer, entry) -> None:
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def issue_zombie(hass: HomeAssistant, entry_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"zombie_{entry_id}")


# --- Un incurable por canario o por stale no se cura con el ratio sano -------

# `cooldown_hours: 1` para que la escalera entera quepa en pocas horas de reloj.
def CANARIO(ids):  # noqa: N802
    return {"canary_entities": [ids[0]], "canary_minutes": 5, "cooldown_hours": 1}


async def test_canario_muerto_no_se_da_por_curado(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Sonda T4: un canario muerto 6 h en un entry con 9 de 10 entidades vivas."""
    caso = await vigilar(CANARIO)
    otro, canario = caso["otro"], caso["ids"][0]
    coordinator = caso["entry"].runtime_data

    hass.states.async_set(canario, "unavailable")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 6 * 60)

    watch = coordinator._watch[otro.entry_id]
    assert len(caso["reloads"]) == 3, caso["reloads"]
    assert len(caso["incurables"]) == 1, caso["incurables"]
    assert caso["curadas"] == [], f"velador_healed falso: {caso['curadas']}"
    assert coordinator._healed_total == 0
    assert watch.incurable is True
    assert watch.flapping is False, "flapping falso: nunca revivió"
    assert issue_zombie(hass, otro.entry_id) is not None, "se borró el Repair del incurable"

    # `unknown` es lo que deja un reload a medias, no una vuelta.
    hass.states.async_set(canario, "unknown")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 10)
    assert caso["curadas"] == [], "un canario en unknown no revivió"

    # Ahora sí vuelve: esa es la curación, una sola, y cierra el incidente.
    hass.states.async_set(canario, "on")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 30)

    assert len(caso["curadas"]) == 1, caso["curadas"]
    assert coordinator._healed_total == 1
    assert watch.incurable is False
    assert watch.reload_attempts == 0
    assert issue_zombie(hass, otro.entry_id) is None

    await bajar(hass, freezer, caso["entry"])


async def test_stale_manual_no_se_da_por_curado(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Sonda T8: un sensor congelado mientras sus hermanos siguen reportando."""
    caso = await vigilar(
        lambda ids: {"stale_entities": [ids[0]], "stale_minutes": 60, "cooldown_hours": 1}
    )
    otro, ids = caso["otro"], caso["ids"]
    congelado = ids[0]
    coordinator = caso["entry"].runtime_data

    def _hermanos_reportan() -> None:
        for entity_id in ids[1:]:
            hass.states.async_set(entity_id, "on", force_update=True)

    await avanzar(hass, freezer, 8 * 60, _hermanos_reportan)

    watch = coordinator._watch[otro.entry_id]
    assert len(caso["reloads"]) == 3, caso["reloads"]
    assert len(caso["incurables"]) == 1, caso["incurables"]
    assert caso["curadas"] == [], f"velador_healed falso: {caso['curadas']}"
    assert coordinator._healed_total == 0
    assert watch.flapping is False
    assert issue_zombie(hass, otro.entry_id) is not None

    # El congelado vuelve a reportar: una curación, la de verdad.
    hass.states.async_set(congelado, "on", force_update=True)
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 10, _hermanos_reportan)

    assert len(caso["curadas"]) == 1, caso["curadas"]
    assert watch.incurable is False
    assert watch.reload_attempts == 0
    assert issue_zombie(hass, otro.entry_id) is None

    await bajar(hass, freezer, caso["entry"])


async def test_la_senal_del_incurable_sobrevive_al_reinicio(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Si no se persiste quién declaró el incurable, el restart lo olvida y el
    siguiente escaneo lo vuelve a dar por curado con el ratio sano."""
    caso = await vigilar(CANARIO)
    otro, canario = caso["otro"], caso["ids"][0]

    hass.states.async_set(canario, "unavailable")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 6 * 60)
    assert caso["entry"].runtime_data._watch[otro.entry_id].incurable is True

    # Que el Store escriba, y recargar Velador como lo hace un cambio de opciones.
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(caso["entry"].entry_id)
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 30)

    watch = caso["entry"].runtime_data._watch[otro.entry_id]
    assert caso["curadas"] == [], f"velador_healed falso tras recargar: {caso['curadas']}"
    assert watch.incurable is True
    assert issue_zombie(hass, otro.entry_id) is not None

    await bajar(hass, freezer, caso["entry"])


# --- cooldown_hours es el último escalón ------------------------------------


async def _zombie_por_ratio(hass, vigilar, freezer, cooldown: int, horas: int) -> dict:
    caso = await vigilar({"cooldown_hours": cooldown})
    for entity_id in caso["ids"]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, horas * 60)
    return caso


async def test_cooldown_largo_retrasa_el_veredicto(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Sonda T2 con 48 h: antes el incurable llegaba a los ~175 min igual que con 1 h."""
    caso = await _zombie_por_ratio(hass, vigilar, freezer, cooldown=48, horas=24)

    assert len(caso["reloads"]) == 3, caso["reloads"]
    assert caso["incurables"] == [], (
        f"cooldown_hours=48 ignorado: incurable a los {caso['incurables']} min"
    )

    await bajar(hass, freezer, caso["entry"])


async def test_cooldown_corto_es_la_espera_tras_el_ultimo_reload(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Con 1 h, el veredicto espera ~1 h (jitter 0.9–1.15) tras el tercer reload."""
    caso = await _zombie_por_ratio(hass, vigilar, freezer, cooldown=1, horas=8)

    assert len(caso["reloads"]) == 3, caso["reloads"]
    assert len(caso["incurables"]) == 1, caso["incurables"]
    espera = caso["incurables"][0] - caso["reloads"][-1]
    assert espera >= 54, f"el veredicto no esperó el último escalón: {espera} min"

    await bajar(hass, freezer, caso["entry"])


# --- La memoria sobrevive a un entry que no está cargado ---------------------


def _reload_que_no_levanta(hass: HomeAssistant, caso: dict):
    """El reload deja al entry en SETUP_RETRY (su nube sigue caída) y Home
    Assistant lo vuelve a cargar dos escaneos después, igual de muerto.

    Devuelve el `cada_paso` que hace de reintento nativo de HA.
    """
    otro = caso["otro"]
    pasos = {"en_retry": 0}

    def _tras_reload() -> None:
        otro.mock_state(hass, ConfigEntryState.SETUP_RETRY)
        pasos["en_retry"] = 0

    def _cada_paso() -> None:
        if otro.state is not ConfigEntryState.SETUP_RETRY:
            return
        pasos["en_retry"] += 1
        if pasos["en_retry"] > 2:
            otro.mock_state(hass, ConfigEntryState.LOADED)

    caso["tras_reload"] = _tras_reload
    return _cada_paso


async def test_la_escalera_no_se_reinicia_si_el_reload_deja_setup_retry(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Un escaneo con el entry en SETUP_RETRY borraba su WatchState y su Repair:
    cada reload volvía a ser el «intento 1» y el incurable no llegaba nunca."""
    caso = await vigilar({"cooldown_hours": 1})
    otro = caso["otro"]
    coordinator = caso["entry"].runtime_data
    reintento_de_ha = _reload_que_no_levanta(hass, caso)
    for entity_id in caso["ids"]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()

    # Primer reload y dos escaneos con el entry sin cargar.
    await avanzar(hass, freezer, 20)
    assert otro.state is ConfigEntryState.SETUP_RETRY
    assert caso["reloads"] == [10]
    watch = coordinator._watch.get(otro.entry_id)
    assert watch is not None, "se borró la memoria de un entry en SETUP_RETRY"
    assert watch.reload_attempts == 1
    assert issue_zombie(hass, otro.entry_id) is not None, "se borró el Repair"
    # El Repair sigue en pie, así que el sensor también lo cuenta.
    assert [z["entry_id"] for z in coordinator.data.zombies] == [otro.entry_id]

    await avanzar(hass, freezer, 8 * 60, reintento_de_ha)

    assert len(caso["reloads"]) == 3, f"la escalera se reinició: {caso['reloads']}"
    assert len(caso["incurables"]) == 1, caso["incurables"]
    assert coordinator._watch[otro.entry_id].incurable is True

    await bajar(hass, freezer, caso["entry"])


async def test_vuelve_sano_de_setup_retry_y_cuenta_como_curacion(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """El reload de Velador lo dejó en SETUP_RETRY y el reintento de HA lo
    levantó sano: antes esa curación se perdía (ni evento, ni heal_log)."""
    caso = await vigilar({"cooldown_hours": 1})
    otro = caso["otro"]
    coordinator = caso["entry"].runtime_data
    caso["tras_reload"] = lambda: otro.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    for entity_id in caso["ids"]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 20)
    assert caso["reloads"] == [10]

    otro.mock_state(hass, ConfigEntryState.LOADED)
    for entity_id in caso["ids"]:
        hass.states.async_set(entity_id, "on")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 10)

    assert len(caso["curadas"]) == 1, caso["curadas"]
    watch = coordinator._watch[otro.entry_id]
    assert [c["attempts"] for c in watch.heal_log] == [1]
    assert issue_zombie(hass, otro.entry_id) is None
    assert coordinator.data.zombies == []

    await bajar(hass, freezer, caso["entry"])


async def test_un_entry_deshabilitado_si_se_olvida(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Lo que no cambia: deshabilitar a mano una integración es decir «ya no
    la vigiles», y ahí sí se sueltan la memoria y el Repair."""
    caso = await _zombie_por_ratio(hass, vigilar, freezer, cooldown=1, horas=8)
    otro = caso["otro"]
    coordinator = caso["entry"].runtime_data
    assert coordinator._watch[otro.entry_id].incurable is True

    # A mano y no con `async_set_disabled_by`: ese pasa por `async_reload`, que
    # el fixture sustituye, y la entry se quedaría cargada.
    object.__setattr__(otro, "disabled_by", ConfigEntryDisabler.USER)
    otro.mock_state(hass, ConfigEntryState.NOT_LOADED)
    await avanzar(hass, freezer, 10)

    assert otro.entry_id not in coordinator._watch
    assert issue_zombie(hass, otro.entry_id) is None
    assert coordinator.data.incurables == []

    await bajar(hass, freezer, caso["entry"])


# --- Un entry que deja de ser vigilable no se queda con el incidente abierto --


async def test_incurable_que_queda_bajo_el_minimo_se_cierra_sin_curacion(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """La casa de origen tenía un incurable con 108 intentos que no salía en
    ningún sensor. La firma coincide con un entry que ya no llega a
    `min_entities` (no se pudo ver su registry): el escaneo no lo juzga, y
    nada puede cerrarle el incidente ni el Repair."""
    caso = await _zombie_por_ratio(hass, vigilar, freezer, cooldown=1, horas=8)
    otro = caso["otro"]
    coordinator = caso["entry"].runtime_data
    watch = coordinator._watch[otro.entry_id]
    assert watch.incurable is True
    recargas = len(caso["reloads"])

    # Le quitan entidades: quedan 2, y el mínimo para vigilar es 3.
    registry = er.async_get(hass)
    for entity_id in caso["ids"][2:]:
        registry.async_remove(entity_id)
        hass.states.async_remove(entity_id)
    await hass.async_block_till_done()

    # No al primer escaneo: a mitad de un reload también faltan entidades.
    await avanzar(hass, freezer, 10)
    assert watch.incurable is True
    assert issue_zombie(hass, otro.entry_id) is not None

    await avanzar(hass, freezer, 40)

    assert watch.incurable is False
    assert watch.reload_attempts == 0
    assert watch.zombie_since is None
    assert issue_zombie(hass, otro.entry_id) is None, "el Repair quedó huérfano"
    assert caso["curadas"] == [], "nadie lo curó: no hay velador_healed"
    assert coordinator._healed_total == 0
    assert watch.heal_log == []
    assert len(caso["reloads"]) == recargas

    await bajar(hass, freezer, caso["entry"])


async def test_incurable_por_canario_en_entry_chico_no_se_cierra_solo(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Un canario cura a su entry aunque tenga menos entidades que el mínimo:
    ese incidente no es de ratio y solo lo cierra el canario al volver."""
    caso = await vigilar(CANARIO, n=2)
    otro, canario = caso["otro"], caso["ids"][0]
    coordinator = caso["entry"].runtime_data

    hass.states.async_set(canario, "unavailable")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 8 * 60)

    watch = coordinator._watch[otro.entry_id]
    assert len(caso["reloads"]) == 3, caso["reloads"]
    assert watch.incurable is True
    assert watch.reload_attempts == 3
    assert issue_zombie(hass, otro.entry_id) is not None
    assert caso["curadas"] == []

    await bajar(hass, freezer, caso["entry"])


# --- La WAN que vuelve libera cooldowns, pero no el probe del incurable -------

WAN = "binary_sensor.wan_prueba"


async def _parpadea_la_wan(hass: HomeAssistant, freezer, veces: int) -> None:
    for _ in range(veces):
        hass.states.async_set(WAN, "off")
        await avanzar(hass, freezer, 10)
        hass.states.async_set(WAN, "on")
        await avanzar(hass, freezer, 10)


async def test_la_wan_que_parpadea_no_recarga_al_incurable(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Cada vuelta de la WAN ponía `last_reload` en None a todos, incurables
    incluidos: cuatro parpadeos en 80 minutos eran cuatro reloads a algo que
    ya había agotado la escalera y toca una vez cada 24 h."""
    hass.states.async_set(WAN, "on")
    caso = await vigilar({"cooldown_hours": 1, "wan_entity": WAN})
    for entity_id in caso["ids"]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 8 * 60)
    watch = caso["entry"].runtime_data._watch[caso["otro"].entry_id]
    assert watch.incurable is True
    recargas = len(caso["reloads"])

    await _parpadea_la_wan(hass, freezer, 4)

    assert caso["reloads"][recargas:] == [], "reloads extra por la WAN"

    # El probe espaciado sigue: uno por día, no más.
    await avanzar(hass, freezer, 3 * 24 * 60)
    assert len(caso["reloads"]) - recargas == 3, caso["reloads"]

    await bajar(hass, freezer, caso["entry"])


async def test_la_wan_que_vuelve_si_libera_el_backoff_de_un_zombie(
    hass: HomeAssistant, vigilar, freezer
) -> None:
    """Lo que no cambia: un zombie a media escalera recibe su reload en cuanto
    vuelve el internet, sin esperar el backoff (30 min tras el primero)."""
    hass.states.async_set(WAN, "on")
    caso = await vigilar({"cooldown_hours": 1, "wan_entity": WAN})
    for entity_id in caso["ids"]:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    await avanzar(hass, freezer, 10)
    assert caso["reloads"] == [10]

    hass.states.async_set(WAN, "off")
    await avanzar(hass, freezer, 5)
    hass.states.async_set(WAN, "on")
    await avanzar(hass, freezer, 5)

    assert caso["reloads"] == [10, 20], caso["reloads"]

    await bajar(hass, freezer, caso["entry"])
