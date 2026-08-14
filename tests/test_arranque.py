"""Que Velador cargue y que lo que lee de Home Assistant exista de verdad."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.velador.const import DOMAIN


async def test_carga_y_expone_sus_entidades(hass: HomeAssistant, velador) -> None:
    """El humo básico: si esto falla, nada más de la suite significa algo."""
    # Los ids salen en inglés: el arnés de HA corre en `en`, la casa de origen
    # está en español. Los nombres visibles vienen de translations/.
    for entity_id in (
        "sensor.velador_zombies",
        "sensor.velador_stale",
        "sensor.velador_recurring_surges",
        "sensor.velador_healed_total",
        "binary_sensor.velador_problem",
    ):
        assert hass.states.get(entity_id) is not None, f"falta {entity_id}"


async def test_la_foto_guarda_la_version_real_de_ha(hass: HomeAssistant, velador) -> None:
    """El bug de v0.7, que vivió tres versiones y ningún stub pudo ver.

    Se leía de `hass.config.version` con fallback `or "?"`. Contra HA de
    verdad ese atributo no existe, así que la foto guardaba "?" y la
    comparación `"?" != "?"` no podía disparar nunca. Contra un doble que sí
    lo tenía, pasaba. Esta prueba es la que faltaba.
    """
    coordinator = velador.runtime_data
    # La foto solo se toma con HA un rato arriba: retratar un arranque a medias
    # produciría un diff falso en el siguiente reinicio.
    coordinator._started = dt_util.utcnow() - timedelta(hours=1)
    coordinator._tomar_snapshot({"un_entry": "Un Entry"})

    assert coordinator._snapshot, "no se tomó la foto"
    assert coordinator._snapshot["ha_version"] == HA_VERSION
    assert coordinator._snapshot["ha_version"] != "?"


async def test_hass_config_no_tiene_version(hass: HomeAssistant) -> None:
    """Guardia explícita contra el atributo que nunca existió.

    Si algún día HA lo agrega, esta prueba falla y avisa que el comentario
    del CHANGELOG de v0.9.2 dejó de ser cierto. Mientras tanto documenta por
    qué no se puede confiar en `getattr(..., None)` para leer de HA.
    """
    assert not hasattr(hass.config, "version")


async def test_el_servicio_de_auditoria_responde(hass: HomeAssistant, velador) -> None:
    """`velador.audit` es el contrato con quien automatiza; que no se rompa."""
    respuesta = await hass.services.async_call(
        DOMAIN, "audit", {}, blocking=True, return_response=True
    )
    assert isinstance(respuesta, dict)
    assert "watched" in respuesta
