"""Los diagnósticos se pegan en issues públicos: no pueden llevar títulos.

frenck lo señaló al aprobar hacs/default#9763: el snapshot y el estado de
vigilancia guardan el título de cada config entry, y muchas integraciones usan
el correo de la cuenta como título.
"""

from __future__ import annotations

import json
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.velador.diagnostics import async_get_config_entry_diagnostics

CORREO = "oscar.prueba@example.com"


async def test_los_diagnosticos_no_llevan_titulos(
    hass: HomeAssistant, velador, integracion
) -> None:
    entry, ids = await integracion(titulo=CORREO)
    # Todas sus entidades muertas: entra al estado de vigilancia con su título.
    for entity_id in ids:
        hass.states.async_set(entity_id, "unavailable")
    coordinator = velador.runtime_data
    await coordinator.async_refresh()
    # Y a la foto post-arranque, que guarda título por entry.
    coordinator._started = dt_util.utcnow() - timedelta(hours=1)
    coordinator._tomar_snapshot({entry.entry_id: CORREO})

    crudo = json.dumps(
        {"snapshot": coordinator.audit_snapshot(), "state": coordinator._dump_state()},
        default=str,
    )
    assert CORREO in crudo, "la prueba ya no ejercita el caso: el título no llegó"

    diag = json.dumps(
        await async_get_config_entry_diagnostics(hass, velador), default=str
    )
    assert CORREO not in diag
    assert f"hub_prueba {entry.entry_id}" in diag


def test_un_titulo_viejo_con_correo_se_redacta() -> None:
    """La foto recuerda entries que ya no existen: su título no está en el mapa."""
    from custom_components.velador.diagnostics import _redactar

    salida = _redactar({"perdidas": [{"title": "viejo@example.com", "motivo": "x"}]}, [])
    assert salida == {"perdidas": [{"title": "**REDACTED**", "motivo": "x"}]}


def test_un_titulo_corto_no_rompe_entity_ids() -> None:
    import re

    from custom_components.velador.diagnostics import _redactar

    subs = [(re.compile(r"(?<![\w.@-])Sun(?![\w@-])"), "sun abc")]
    salida = _redactar({"x": "sensor.Sun_next", "y": "Sun", "z": "zombies: Sun, Hue"}, subs)
    assert salida == {"x": "sensor.Sun_next", "y": "sun abc", "z": "zombies: sun abc, Hue"}
