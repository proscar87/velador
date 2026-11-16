"""Reautenticaciones resueltas y memoria acotada de curaciones."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.velador.const import DOMAIN
from custom_components.velador.coordinator import WatchState


@pytest.mark.parametrize("pendiente", [False, True])
async def test_reauth_manual_con_pocas_entidades(hass, velador, integracion, pendiente):
    entry, _ = await integracion(n=1)
    coordinator = velador.runtime_data
    watch = coordinator._watch.setdefault(entry.entry_id, WatchState())
    with patch.object(coordinator, "_reauth_pending", return_value=True):
        await coordinator._maybe_heal(entry, watch, {})
    registro = ir.async_get(hass)
    assert watch.needs_reauth
    assert registro.async_get_issue(DOMAIN, f"reauth_{entry.entry_id}")
    with patch.object(coordinator, "_reauth_pending", return_value=pendiente):
        await coordinator.async_refresh()
    assert watch.needs_reauth is pendiente
    assert (watch.reauth_since is not None) is pendiente
    assert bool(registro.async_get_issue(DOMAIN, f"reauth_{entry.entry_id}")) is pendiente


@pytest.mark.parametrize("horas", [2, 30])
async def test_curacion_y_recaida(hass, velador, integracion, horas):
    entry, ids = await integracion()
    coordinator = velador.runtime_data
    ahora = dt_util.utcnow()
    watch = WatchState(zombie_since=ahora - timedelta(minutes=15), reload_attempts=2, senal="ratio")
    coordinator._watch[entry.entry_id] = watch
    with patch("custom_components.velador.coordinator.dt_util.utcnow", return_value=ahora):
        coordinator._on_healed(entry, watch)
    assert watch.heal_log == [{"at": ahora.isoformat(), "downtime_min": 15, "attempts": 2, "senal": "ratio", "recaida_min": None}]
    watch.strikes = 0
    watch.zombie_since = None
    for eid in ids:
        hass.states.async_set(eid, "unavailable")
    with patch("custom_components.velador.coordinator.dt_util.utcnow", return_value=ahora + timedelta(hours=horas)), patch.object(coordinator, "_maybe_heal"):
        for _ in range(3):
            await coordinator.async_refresh()
    assert watch.heal_log[-1]["recaida_min"] == (120 if horas == 2 else None)
    resumen = coordinator.audit_snapshot()["curaciones"]
    assert resumen == {"curaciones_registradas": 1, "con_recaida_24h": int(horas == 2)}


async def test_historial_acotado_y_persistencia(hass, velador, integracion):
    entry, _ = await integracion()
    watch = WatchState()
    for _ in range(25):
        velador.runtime_data._on_healed(entry, watch)
    assert len(watch.heal_log) == 20
    assert WatchState.from_dict(watch.as_dict()).heal_log == watch.heal_log
    assert WatchState.from_dict({}).heal_log == []
