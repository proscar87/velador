"""Fixtures compartidas.

Las pruebas corren contra Home Assistant de verdad, no contra dobles. Es más
lento y pesa medio giga de dependencias, pero es la única forma de cazar la
clase de bug que dejó muerta la detección de breaking change de v0.7 durante
tres versiones: el código leía `hass.config.version`, un atributo que no
existe, y el stub —que sí lo tenía— juraba que todo estaba bien.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    async_fire_time_changed,
    mock_integration,
)

from custom_components.velador.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Sin esto HA no mira en custom_components/."""
    yield


@pytest.fixture
def opciones() -> dict:
    """Opciones por defecto para las pruebas.

    `grace_minutes: 0` porque la gracia post-arranque hace que todo escaneo
    devuelva vacío durante 15 minutos: en producción evita diagnosticar una
    casa a medio arrancar, en una prueba solo esconde el resultado.
    """
    return {"grace_minutes": 0}


@pytest.fixture
async def velador(hass: HomeAssistant, opciones: dict):
    """Velador montado por HA como en una casa: setup real, entidades reales.

    Se descarga al final porque el coordinator deja un temporizador de refresco
    corriendo, y el arnés de HA falla la prueba si algo queda vivo — que es
    justo la clase de fuga que uno quiere que se note.
    """
    entry = MockConfigEntry(domain=DOMAIN, title="Velador", options=opciones)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    # Dejar que el Store haga su escritura diferida antes de bajar todo: si no,
    # queda agendada y el arnés la reporta como fuga (y tendría razón).
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def integracion(hass: HomeAssistant):
    """Fabrica una integración vigilable con N entidades registradas.

    Devuelve (entry, [entity_id...]). Las entidades quedan en el registry de
    verdad y con estado de verdad, que es lo que el coordinator consulta.

    El dominio es inventado y el módulo se registra falso: con `hue` de
    verdad, HA intenta importarla al bajar la prueba y revienta buscando
    `aiohue`. El estado se fuerza a LOADED porque Velador solo mira entries
    cargadas — una que no cargó es otro caso, con su propia rama.
    """

    async def _hacer(dominio: str = "hub_prueba", n: int = 100, titulo: str = "Hub"):
        mock_integration(
            hass,
            MockModule(
                dominio,
                async_setup_entry=AsyncMock(return_value=True),
                async_unload_entry=AsyncMock(return_value=True),
            ),
        )
        entry = MockConfigEntry(domain=dominio, title=titulo)
        entry.add_to_hass(hass)
        # Montarla de verdad exigiría registrarle un config flow, y no aporta
        # nada aquí: lo que Velador consulta es el estado y las entidades.
        entry.mock_state(hass, ConfigEntryState.LOADED)

        registry = er.async_get(hass)
        ids = []
        for i in range(n):
            reg_entry = registry.async_get_or_create(
                "light", dominio, f"{entry.entry_id}_{i}", config_entry=entry
            )
            hass.states.async_set(reg_entry.entity_id, "on")
            ids.append(reg_entry.entity_id)
        await hass.async_block_till_done()
        return entry, ids

    return _hacer
