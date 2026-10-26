"""Diagnostics de Velador: la tabla de vigilancia completa en un JSON.

Un issue de GitHub con diagnóstico descargable en vez de ping-pong de logs.

Los títulos de las demás config entries se reemplazan por `<dominio> <entry_id>`:
el diagnóstico se pega en issues públicos y muchas integraciones usan el correo
de la cuenta como título (señalado por frenck en hacs/default#9763).
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

# Claves que guardan títulos aunque la entry ya no exista (la foto post-arranque
# recuerda lo que había antes del reinicio).
_CLAVES_TITULO = {"title", "titles", "titulo"}
_REDACTADO = "**REDACTED**"


def _sustituciones(hass: HomeAssistant) -> list[tuple[re.Pattern[str], str]]:
    """Cada título conocido, del más largo al más corto, con su reemplazo."""
    pares = {
        ce.title: f"{ce.domain} {ce.entry_id}"
        for ce in hass.config_entries.async_entries()
        if ce.title
    }
    return [
        # Delimitado: un título corto no debe comerse un pedazo de un entity_id.
        (re.compile(rf"(?<![\w.@-]){re.escape(titulo)}(?![\w@-])"), reemplazo)
        for titulo, reemplazo in sorted(pares.items(), key=lambda p: -len(p[0]))
    ]


def _redactar(valor: Any, subs: list[tuple[re.Pattern[str], str]], clave: str = "") -> Any:
    if isinstance(valor, dict):
        return {
            _redactar(k, subs): _redactar(v, subs, k if isinstance(k, str) else "")
            for k, v in valor.items()
        }
    if isinstance(valor, (list, tuple, set)):
        return [_redactar(v, subs, clave) for v in valor]
    if isinstance(valor, str):
        for patron, reemplazo in subs:
            valor = patron.sub(reemplazo, valor)
        if clave in _CLAVES_TITULO and "@" in valor:
            return _REDACTADO
        return valor
    return valor


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    coordinator = entry.runtime_data
    return _redactar(
        {
            "options": dict(entry.options),
            "snapshot": coordinator.audit_snapshot(),
            "watch_state": coordinator._dump_state(),  # noqa: SLF001 — mismo paquete
        },
        _sustituciones(hass),
    )
