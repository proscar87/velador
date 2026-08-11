"""Coordinator de Velador: detecta y revive integraciones zombie.

Un zombie es un config entry en estado LOADED cuyas entidades están
mayoritariamente unavailable — Home Assistant lo reporta como sano y no
hay nada nativo que lo detecte. Patrón observado tras apagones, restarts
y caídas de nube: la integración "carga" pero queda muerta por dentro.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.components.automation import automations_with_entity
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import (
    ALWAYS_IGNORED_DOMAINS,
    AUTO_STALE_FLOOR_MINUTES,
    AUTO_STALE_MULTIPLIER,
    BACKOFF_MINUTES,
    CADENCE_MIN_SAMPLES,
    CADENCE_SAMPLES,
    CONF_AUTO_STALE,
    DEFAULT_AUTO_STALE,
    EVENT_AUTO_STALE,
    CONF_CANARY_ENTITIES,
    CONF_CANARY_MINUTES,
    CONF_DEVICE_ZOMBIE_HOURS,
    CONF_STALE_ENTITIES,
    CONF_STALE_MINUTES,
    CONF_WAN_ENTITY,
    DEFAULT_CANARY_MINUTES,
    DEFAULT_DEVICE_ZOMBIE_HOURS,
    EVENT_DEBOUNCE_SECONDS,
    EVENT_DEVICE_ZOMBIE,
    EVENT_FLAPPING,
    EVENT_REAUTH_NEEDED,
    EVENT_RESTART_DIFF,
    EVENT_STORM_DETECTED,
    SNAPSHOT_MIN_AGE_MINUTES,
    FLAP_MAX_HEALS,
    FLAP_WINDOW_HOURS,
    HUB_DOMAINS_NO_RELOAD,
    INCURABLE_RETRY_HOURS,
    MAX_RELOAD_ATTEMPTS,
    PROBE_DELAY_SECONDS,
    STORM_RELOAD_SPACING_SECONDS,
    STORM_THRESHOLD,
    DEFAULT_STALE_MINUTES,
    EVENT_STALE_DETECTED,
    EVENT_STALE_RECOVERED,
    CONF_AUTO_HEAL,
    CONF_COOLDOWN_HOURS,
    CONF_EXCLUDE_DOMAINS,
    CONF_GRACE_MINUTES,
    CONF_MIN_ENTITIES,
    CONF_STRIKES,
    CONF_THRESHOLD,
    DEFAULT_AUTO_HEAL,
    DEFAULT_COOLDOWN_HOURS,
    DEFAULT_GRACE_MINUTES,
    DEFAULT_MIN_ENTITIES,
    DEFAULT_STRIKES,
    DEFAULT_THRESHOLD,
    DOMAIN,
    EVENT_HEALED,
    EVENT_INCURABLE,
    EVENT_ZOMBIE_DETECTED,
    SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.state"
SAVE_DELAY_SECONDS = 10


@dataclass
class WatchState:
    """Estado de vigilancia de un config entry."""

    strikes: int = 0
    last_reload: datetime | None = None
    reload_attempts: int = 0
    incurable: bool = False
    needs_reauth: bool = False
    healed_count: int = 0
    zombie_since: datetime | None = None
    heal_history: list[datetime] = field(default_factory=list)
    flapping: bool = False
    reauth_since: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "strikes": self.strikes,
            "last_reload": self.last_reload.isoformat() if self.last_reload else None,
            "reload_attempts": self.reload_attempts,
            "incurable": self.incurable,
            "needs_reauth": self.needs_reauth,
            "healed_count": self.healed_count,
            "zombie_since": self.zombie_since.isoformat() if self.zombie_since else None,
            "heal_history": [t.isoformat() for t in self.heal_history],
            "flapping": self.flapping,
            "reauth_since": self.reauth_since.isoformat() if self.reauth_since else None,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "WatchState":
        return cls(
            strikes=int(raw.get("strikes", 0)),
            last_reload=dt_util.parse_datetime(raw["last_reload"])
            if raw.get("last_reload")
            else None,
            reload_attempts=int(raw.get("reload_attempts", 0)),
            incurable=bool(raw.get("incurable", False)),
            needs_reauth=bool(raw.get("needs_reauth", False)),
            healed_count=int(raw.get("healed_count", 0)),
            zombie_since=dt_util.parse_datetime(raw["zombie_since"])
            if raw.get("zombie_since")
            else None,
            heal_history=[
                t
                for t in (
                    dt_util.parse_datetime(x) for x in raw.get("heal_history", [])
                )
                if t
            ],
            flapping=bool(raw.get("flapping", False)),
            reauth_since=dt_util.parse_datetime(raw["reauth_since"])
            if raw.get("reauth_since")
            else None,
        )


@dataclass
class VeladorData:
    """Resultado de un escaneo."""

    zombies: list[dict] = field(default_factory=list)
    incurables: list[dict] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)
    reauth: list[dict] = field(default_factory=list)
    device_zombies: list[dict] = field(default_factory=list)
    watched: int = 0
    healed_total: int = 0
    last_scan: datetime | None = None


class VeladorCoordinator(DataUpdateCoordinator[VeladorData]):
    """Escanea config entries cada SCAN_INTERVAL en busca de zombies."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.entry = entry
        self._watch: dict[str, WatchState] = {}
        self._stale_active: set[str] = set()
        self._iot_class: dict[str, str] = {}
        self._wan_was_down = False
        self._started = dt_util.utcnow()
        self._healed_total = 0
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._last_saved: str | None = None
        self._device_zombies_active: set[str] = set()
        self._event_refresh_pending = False
        # v0.6 — cadencia aprendida: entity_id -> {"gaps": [seg...], "last": iso, "median": seg}
        self._cadence: dict[str, dict] = {}
        self._auto_stale_active: set[str] = set()
        # v0.7 — foto del último estado sano conocido, para el diff post-arranque
        self._snapshot: dict = {}
        self._diff_done = False

    @callback
    def async_start(self) -> "callable":
        """Detección por eventos: transición a unavailable → chequeo con debounce.

        Baja el peor caso de ~15 min (3 scans) a ~1-6 min. El scan periódico
        queda de red de seguridad y para stale/canarios.
        """

        @callback
        def _on_state_changed(event: Event) -> None:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if (
                new_state is None
                or old_state is None
                or new_state.state != "unavailable"
                or old_state.state in ("unavailable", "unknown")
            ):
                return
            if self._event_refresh_pending:
                return
            self._event_refresh_pending = True

            @callback
            def _debounced(_now) -> None:
                self._event_refresh_pending = False
                self.hass.async_create_task(self.async_request_refresh())

            async_call_later(self.hass, EVENT_DEBOUNCE_SECONDS, _debounced)

        return self.hass.bus.async_listen("state_changed", _on_state_changed)

    async def async_service_heal(self, entry_id: str | None = None) -> dict:
        """Servicio velador.heal: forzar el ciclo reseteando strikes/cooldowns.

        Sin entry_id: cura todo lo actualmente enfermo (zombies + incurables).
        Habilita "cuando vuelva la luz, cura todo" como automatización.
        """
        targets: list[str] = []
        if entry_id:
            targets = [entry_id]
        else:
            targets = [
                info["entry_id"]
                for info in (self.data.zombies + self.data.incurables)
            ]
        healed: list[str] = []
        for target in targets:
            config_entry = self.hass.config_entries.async_get_entry(target)
            if config_entry is None:
                continue
            watch = self._watch.setdefault(target, WatchState())
            watch.reload_attempts = 0
            watch.last_reload = None
            watch.incurable = False
            watch.flapping = False
            ir.async_delete_issue(self.hass, DOMAIN, f"flapping_{target}")
            _LOGGER.info(
                "velador.heal: ciclo forzado sobre %s (%s)",
                config_entry.title,
                config_entry.domain,
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(target)
            )
            healed.append(config_entry.title)
        self._save_state()
        return {"healed": healed}

    def audit_snapshot(self) -> dict:
        """Servicio velador.audit: el dict completo, consumible sin parsear atributos."""
        data = self.data
        return {
            "zombies": data.zombies,
            "incurables": data.incurables,
            "stale": data.stale,
            "reauth": data.reauth,
            "device_zombies": data.device_zombies,
            "watched": data.watched,
            "healed_total": data.healed_total,
            "last_scan": data.last_scan.isoformat() if data.last_scan else None,
        }

    async def async_load_state(self) -> None:
        """Restaurar la memoria de strikes/intentos/incurables de un arranque previo.

        Sin esto, cada restart borra lo aprendido: un incurable conocido
        re-quema 2 reloads + cooldowns para re-descubrir su diagnóstico
        (observado en el update a HA 2026.8, 5-ago-2026).
        """
        raw = await self._store.async_load()
        if not raw:
            return
        self._healed_total = int(raw.get("healed_total", 0))
        self._snapshot = raw.get("snapshot") or {}
        for eid, c in (raw.get("cadence") or {}).items():
            try:
                self._cadence[eid] = {
                    "gaps": [],
                    "last": c.get("last"),
                    "median": float(c["median"]),
                }
            except (TypeError, ValueError, KeyError):
                continue
        restored = 0
        for entry_id, watch_raw in (raw.get("watch") or {}).items():
            # Solo restaurar entries que siguen existiendo.
            if self.hass.config_entries.async_get_entry(entry_id) is None:
                continue
            try:
                self._watch[entry_id] = WatchState.from_dict(watch_raw)
                restored += 1
            except (TypeError, ValueError, KeyError):  # dato corrupto: empezar de cero
                continue
        if restored:
            incurables = sum(1 for w in self._watch.values() if w.incurable)
            _LOGGER.info(
                "Memoria restaurada: %s entries (%s incurables conocidos)",
                restored,
                incurables,
            )
        # Los Repairs no sobreviven un restart: re-crear la señal de los
        # incurables/reauth restaurados para que no queden mudos.
        for entry_id, watch in self._watch.items():
            if not (watch.incurable or watch.needs_reauth):
                continue
            config_entry = self.hass.config_entries.async_get_entry(entry_id)
            if config_entry is None:
                continue
            if watch.incurable:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"zombie_{entry_id}",
                    is_fixable=True,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="incurable",
                    translation_placeholders={
                        "title": config_entry.title,
                        "domain": config_entry.domain,
                        "attempts": str(watch.reload_attempts),
                    },
                )
            if watch.needs_reauth:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"reauth_{entry_id}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="reauth",
                    translation_placeholders={
                        "title": config_entry.title,
                        "domain": config_entry.domain,
                    },
                )

    def _dump_state(self) -> dict:
        return {
            "healed_total": self._healed_total,
            "watch": {eid: w.as_dict() for eid, w in self._watch.items()},
            # Solo la mediana y la última marca: reconstruir la ventana de gaps
            # tras un restart no aporta y engordaría el archivo.
            "cadence": {
                eid: {"median": c["median"], "last": c["last"]}
                for eid, c in self._cadence.items()
                if c.get("median")
            },
            "snapshot": self._snapshot,
        }

    def _save_state(self) -> None:
        """Persistir solo si algo cambió (dirty-check para no moler la flash)."""
        snapshot = json.dumps(self._dump_state(), sort_keys=True)
        if snapshot == self._last_saved:
            return
        self._last_saved = snapshot
        self._store.async_delay_save(self._dump_state, SAVE_DELAY_SECONDS)

    def _opt(self, key: str, default):
        return self.entry.options.get(key, default)

    @property
    def _excluded_domains(self) -> set[str]:
        raw = self._opt(CONF_EXCLUDE_DOMAINS, "")
        extra = {d.strip() for d in raw.split(",") if d.strip()}
        return ALWAYS_IGNORED_DOMAINS | extra

    def _reauth_pending(self, entry_id: str) -> bool:
        """Hay un reauth flow abierto para este entry: el reload NO cura eso."""
        for flow in self.hass.config_entries.flow.async_progress():
            ctx = flow.get("context") or {}
            if ctx.get("source") == "reauth" and ctx.get("entry_id") == entry_id:
                return True
        return False

    def _wan_down(self) -> bool:
        wan = self._opt(CONF_WAN_ENTITY, "")
        if not wan:
            return False
        state = self.hass.states.get(wan)
        return state is None or state.state in ("off", "unavailable", "unknown", "not_home")

    async def _is_cloud(self, domain: str) -> bool:
        if domain not in self._iot_class:
            try:
                integration = await async_get_integration(self.hass, domain)
                self._iot_class[domain] = integration.iot_class or ""
            except Exception:  # noqa: BLE001 — dominio raro: tratar como local
                self._iot_class[domain] = ""
        return self._iot_class[domain].startswith("cloud")

    async def _async_update_data(self) -> VeladorData:
        data = VeladorData(healed_total=self._healed_total, last_scan=dt_util.utcnow())

        grace = timedelta(minutes=self._opt(CONF_GRACE_MINUTES, DEFAULT_GRACE_MINUTES))
        if dt_util.utcnow() - self._started < grace:
            # Post-arranque todo parece muerto por unos minutos; no diagnosticar.
            return data

        threshold = self._opt(CONF_THRESHOLD, DEFAULT_THRESHOLD)
        min_entities = self._opt(CONF_MIN_ENTITIES, DEFAULT_MIN_ENTITIES)
        strikes_needed = self._opt(CONF_STRIKES, DEFAULT_STRIKES)
        auto_heal = self._opt(CONF_AUTO_HEAL, DEFAULT_AUTO_HEAL)
        cooldown = timedelta(hours=self._opt(CONF_COOLDOWN_HOURS, DEFAULT_COOLDOWN_HOURS))
        excluded = self._excluded_domains

        wan_down = self._wan_down()
        if self._wan_was_down and not wan_down:
            # Volvió el internet: liberar cooldowns para curación inmediata.
            _LOGGER.info("WAN de vuelta: cooldowns liberados para curación agresiva")
            for watch_state in self._watch.values():
                watch_state.last_reload = None
        self._wan_was_down = wan_down

        registry = er.async_get(self.hass)
        entities_by_entry: dict[str, list[er.RegistryEntry]] = {}
        for reg_entry in registry.entities.values():
            if reg_entry.config_entry_id and not reg_entry.disabled_by:
                entities_by_entry.setdefault(reg_entry.config_entry_id, []).append(reg_entry)

        seen_entry_ids: set[str] = set()
        sanos: dict[str, str] = {}
        new_zombies: list[tuple[ConfigEntry, WatchState, dict]] = []
        heal_queue: list[tuple[ConfigEntry, WatchState, dict]] = []

        for config_entry in self.hass.config_entries.async_entries():
            if config_entry.domain in excluded:
                continue
            setup_error = config_entry.state is ConfigEntryState.SETUP_ERROR
            if config_entry.state is not ConfigEntryState.LOADED and not setup_error:
                # SETUP_RETRY y demás: el retry nativo de HA ya corre; templanza.
                continue

            ents = entities_by_entry.get(config_entry.entry_id, [])
            total = 0
            dead = 0
            dead_examples: list[str] = []
            if setup_error:
                # Entry que no cargó: cero entidades vivas por definición.
                total = dead = max(len(ents), 1)
                dead_examples = [r.entity_id for r in ents[:5]]
            else:
                for reg_entry in ents:
                    state = self.hass.states.get(reg_entry.entity_id)
                    if state is None:
                        continue
                    total += 1
                    if state.state == "unavailable":
                        dead += 1
                        if len(dead_examples) < 5:
                            dead_examples.append(reg_entry.entity_id)

                if total < min_entities:
                    continue

            seen_entry_ids.add(config_entry.entry_id)
            data.watched += 1
            if not setup_error and total and (dead / total) < threshold:
                sanos[config_entry.entry_id] = config_entry.title
            watch = self._watch.setdefault(config_entry.entry_id, WatchState())
            is_zombie = setup_error or (dead / total) >= threshold

            if watch.needs_reauth:
                data.reauth.append(
                    {
                        "entry_id": config_entry.entry_id,
                        "domain": config_entry.domain,
                        "title": config_entry.title,
                        "since": watch.reauth_since.isoformat()
                        if watch.reauth_since
                        else None,
                    }
                )

            if is_zombie and wan_down and await self._is_cloud(config_entry.domain):
                # Sin internet la falla es del entorno: congelar juicio y curas.
                continue

            if not is_zombie:
                if watch.strikes >= strikes_needed or watch.incurable:
                    # Estaba declarado zombie/incurable y revivió.
                    self._on_healed(config_entry, watch)
                watch.strikes = 0
                watch.incurable = False
                watch.zombie_since = None
                self._maybe_clear_flapping(config_entry, watch)
                continue

            watch.strikes += 1
            if watch.strikes < strikes_needed:
                continue
            if watch.zombie_since is None:
                watch.zombie_since = dt_util.utcnow()

            info = {
                "entry_id": config_entry.entry_id,
                "domain": config_entry.domain,
                "title": config_entry.title,
                "dead": dead,
                "total": total,
                "examples": dead_examples,
                "zombie_since": watch.zombie_since.isoformat(),
                "reload_attempts": watch.reload_attempts,
                "setup_error": setup_error,
                "flapping": watch.flapping,
                "automations_ciegas": self._blind_automations(dead_examples),
            }

            if watch.incurable:
                data.incurables.append(info)
                # Circuit breaker half-open: probe espaciado (1×/24h) en vez
                # de terminal — muchos incurables de nube sanan solos.
                if auto_heal:
                    heal_queue.append((config_entry, watch, info))
                continue

            data.zombies.append(info)

            if watch.strikes == strikes_needed:
                new_zombies.append((config_entry, watch, info))

            if auto_heal:
                heal_queue.append((config_entry, watch, info))

        # Modo tormenta: N zombies NUEVOS en el mismo escaneo no son N fallas,
        # es un apagón o caída de red. Un Repair agregado y curación escalonada.
        storm = len(new_zombies) >= STORM_THRESHOLD
        if storm:
            self._on_storm(new_zombies)
        else:
            for storm_entry, _watch, storm_info in new_zombies:
                self._on_zombie_detected(storm_entry, storm_info)

        if heal_queue:
            if storm:
                self.hass.async_create_task(self._heal_sequential(heal_queue))
            else:
                for heal_entry, heal_watch, heal_info in heal_queue:
                    await self._maybe_heal(heal_entry, heal_watch, heal_info)

        if not data.zombies and not data.incurables:
            ir.async_delete_issue(self.hass, DOMAIN, "storm")

        # Limpiar entries que ya no existen.
        for entry_id in list(self._watch):
            if entry_id not in seen_entry_ids:
                del self._watch[entry_id]
                ir.async_delete_issue(self.hass, DOMAIN, f"zombie_{entry_id}")

        await self._scan_canaries(data, wan_down)
        self._diff_post_arranque(sanos)
        self._tomar_snapshot(sanos)
        await self._scan_stale(data, wan_down)
        await self._scan_auto_stale(data)
        await self._scan_device_zombies(data)
        data.healed_total = self._healed_total
        self._save_state()
        return data

    def _blind_automations(self, entity_ids: list[str]) -> list[str]:
        """Radio de daño: automatizaciones que dependen de las entidades muertas."""
        blind: set[str] = set()
        for entity_id in entity_ids:
            try:
                blind.update(automations_with_entity(self.hass, entity_id))
            except Exception:  # noqa: BLE001 — automation no cargado aún
                break
        return sorted(blind)[:10]

    def _maybe_clear_flapping(self, config_entry: ConfigEntry, watch: WatchState) -> None:
        """Liberar el estado inestable cuando la ventana de recaídas quedó vacía."""
        if not watch.flapping:
            return
        now = dt_util.utcnow()
        watch.heal_history = [
            t for t in watch.heal_history if now - t < timedelta(hours=FLAP_WINDOW_HOURS)
        ]
        if len(watch.heal_history) < FLAP_MAX_HEALS:
            watch.flapping = False
            ir.async_delete_issue(self.hass, DOMAIN, f"flapping_{config_entry.entry_id}")
            _LOGGER.info(
                "%s (%s) estable otra vez: auto-heal re-habilitado",
                config_entry.title,
                config_entry.domain,
            )

    def _on_storm(
        self, new_zombies: list[tuple[ConfigEntry, WatchState, dict]]
    ) -> None:
        titles = ", ".join(ce.title for ce, _w, _i in new_zombies)
        at_local = dt_util.now().strftime("%H:%M")
        _LOGGER.warning(
            "MODO TORMENTA: %s integraciones cayeron juntas (%s) — probable "
            "apagón o caída de red; curación escalonada",
            len(new_zombies),
            titles,
        )
        self.hass.bus.async_fire(
            EVENT_STORM_DETECTED,
            {
                "count": len(new_zombies),
                "at": at_local,
                "entries": [info for _ce, _w, info in new_zombies],
            },
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "storm",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="storm",
            translation_placeholders={
                "count": str(len(new_zombies)),
                "titles": titles,
                "time": at_local,
            },
        )

    async def _heal_sequential(
        self, queue: list[tuple[ConfigEntry, WatchState, dict]]
    ) -> None:
        """Reloads espaciados: 10 reloads simultáneos contra un router recién
        booteado producen exactamente el segundo strike falso."""
        for index, (config_entry, watch, info) in enumerate(queue):
            if index:
                await asyncio.sleep(STORM_RELOAD_SPACING_SECONDS)
            await self._maybe_heal(config_entry, watch, info)

    async def _heal_owner(
        self, entry_id: str | None, data: VeladorData, wan_down: bool, info: dict
    ) -> None:
        """Escalera de curación para el entry dueño de una entidad (canario/stale)."""
        if not entry_id:
            return
        config_entry = self.hass.config_entries.async_get_entry(entry_id)
        if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
            return
        if (
            config_entry.domain in self._excluded_domains
            or config_entry.domain in HUB_DOMAINS_NO_RELOAD
        ):
            return
        if wan_down and await self._is_cloud(config_entry.domain):
            return
        if not self._opt(CONF_AUTO_HEAL, DEFAULT_AUTO_HEAL):
            return
        watch = self._watch.setdefault(entry_id, WatchState())
        full_info = {
            "entry_id": entry_id,
            "domain": config_entry.domain,
            "title": config_entry.title,
            **info,
        }
        await self._maybe_heal(config_entry, watch, full_info)

    async def _scan_canaries(self, data: VeladorData, wan_down: bool) -> None:
        """Canarios: entidades críticas que curan su entry sin esperar el ratio.

        Cazan la muerte PARCIAL: 1 CT muerto de 4 jamás llega al 90%.
        """
        watched = self._opt(CONF_CANARY_ENTITIES, [])
        if not watched:
            return
        max_age = timedelta(minutes=self._opt(CONF_CANARY_MINUTES, DEFAULT_CANARY_MINUTES))
        now = dt_util.utcnow()
        registry = er.async_get(self.hass)
        healed: set[str] = set()
        for entity_id in watched:
            state = self.hass.states.get(entity_id)
            if state is None or state.state != "unavailable":
                continue
            if now - state.last_changed < max_age:
                continue
            reg = registry.entities.get(entity_id)
            entry_id = reg.config_entry_id if reg else None
            if not entry_id or entry_id in healed:
                continue
            healed.add(entry_id)
            await self._heal_owner(
                entry_id,
                data,
                wan_down,
                {
                    "canario": entity_id,
                    "muerto_min": int((now - state.last_changed).total_seconds() // 60),
                },
            )

    async def _scan_stale(self, data: VeladorData, wan_down: bool) -> None:
        """Sensores congelados: reportan un valor viejo sin ponerse unavailable.

        Usa last_reported (no last_updated): un sensor sano que repite el
        mismo valor sigue reportando; el congelado dejó de reportar.
        """
        watched = self._opt(CONF_STALE_ENTITIES, [])
        if not watched:
            return
        max_age = timedelta(minutes=self._opt(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES))
        now = dt_util.utcnow()

        for entity_id in watched:
            state = self.hass.states.get(entity_id)
            issue_id = f"stale_{entity_id}"
            if state is None or state.state in ("unavailable", "unknown"):
                # Muerto visible: eso lo cubre la detección zombie, no es stale.
                self._stale_recover(entity_id, issue_id, silent=True)
                continue
            reported = getattr(state, "last_reported", None) or state.last_updated
            age = now - reported
            if age <= max_age:
                self._stale_recover(entity_id, issue_id, silent=False)
                continue

            info = {
                "entity_id": entity_id,
                "state": state.state,
                "last_reported": reported.isoformat(),
                "minutes_stale": int(age.total_seconds() // 60),
            }
            data.stale.append(info)
            reg = er.async_get(self.hass).entities.get(entity_id)
            await self._heal_owner(
                reg.config_entry_id if reg else None, data, wan_down, {"stale": entity_id}
            )
            if entity_id not in self._stale_active:
                self._stale_active.add(entity_id)
                _LOGGER.warning(
                    "Sensor congelado: %s lleva %s min reportando '%s'",
                    entity_id,
                    info["minutes_stale"],
                    state.state,
                )
                self.hass.bus.async_fire(EVENT_STALE_DETECTED, info)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="stale",
                    translation_placeholders={
                        "entity_id": entity_id,
                        "minutes": str(info["minutes_stale"]),
                        "state": state.state,
                    },
                )

    async def _scan_device_zombies(self, data: VeladorData) -> None:
        """Zombies a nivel device: el punto ciego matemático del ratio.

        3 sensores muertos de 40 = 7%, integración "sana", y la luz del baño
        no prende. Señal pura, sin auto-heal — un device no se recarga.
        """
        hours = self._opt(CONF_DEVICE_ZOMBIE_HOURS, DEFAULT_DEVICE_ZOMBIE_HOURS)
        if not hours:
            return
        max_age = timedelta(hours=hours)
        now = dt_util.utcnow()
        registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        excluded = self._excluded_domains

        by_device: dict[str, list] = {}
        for reg_entry in registry.entities.values():
            if not reg_entry.device_id or reg_entry.disabled_by:
                continue
            by_device.setdefault(reg_entry.device_id, []).append(reg_entry)

        current: set[str] = set()
        for device_id, ents in by_device.items():
            states = [self.hass.states.get(r.entity_id) for r in ents]
            states = [s for s in states if s is not None]
            if len(states) < 2:
                continue
            if not all(
                s.state == "unavailable" and now - s.last_changed > max_age
                for s in states
            ):
                continue
            device = device_registry.async_get(device_id)
            if device is None:
                continue
            if any(
                self.hass.config_entries.async_get_entry(ce_id) is not None
                and self.hass.config_entries.async_get_entry(ce_id).domain in excluded
                for ce_id in device.config_entries
            ):
                continue
            area = (
                area_registry.async_get_area(device.area_id) if device.area_id else None
            )
            info = {
                "device_id": device_id,
                "name": device.name_by_user or device.name,
                "area": area.name if area else None,
                "entities": [s.entity_id for s in states][:8],
                "dead_hours": int(
                    max(
                        (now - s.last_changed).total_seconds() for s in states
                    )
                    // 3600
                ),
            }
            data.device_zombies.append(info)
            current.add(device_id)
            if device_id not in self._device_zombies_active:
                self.hass.bus.async_fire(EVENT_DEVICE_ZOMBIE, info)
                _LOGGER.warning(
                    "Device muerto: %s (%s) — %s entidades unavailable > %sh",
                    info["name"],
                    info["area"] or "sin área",
                    len(states),
                    hours,
                )
        self._device_zombies_active = current
        if current:
            names = ", ".join(
                f"{d['name']} ({d['area']})" if d["area"] else str(d["name"])
                for d in data.device_zombies[:10]
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "device_zombies",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="device_zombies",
                translation_placeholders={
                    "count": str(len(current)),
                    "names": names,
                    "hours": str(hours),
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "device_zombies")

    def _tomar_snapshot(self, sanos: dict[str, str]) -> None:
        """Guarda la foto de lo que está sano ahora, para comparar tras el próximo boot.

        Solo se fotografía cuando HA lleva un rato arriba: retratar un arranque a
        medias produciría un diff falso en el siguiente reinicio.
        """
        if dt_util.utcnow() - self._started < timedelta(minutes=SNAPSHOT_MIN_AGE_MINUTES):
            return
        self._snapshot = {
            "at": dt_util.utcnow().isoformat(),
            "ha_version": getattr(self.hass.config, "version", None) or "?",
            "entries": sanos,
        }

    def _diff_post_arranque(self, sanos: dict[str, str]) -> None:
        """Compara contra la última foto sana: qué se cayó y no volvió tras el restart.

        Es el hueco que dejaba el resto de la vigilancia: si una integración
        desaparece o queda muerta justo en el reinicio, nadie lo relaciona con el
        reinicio. Aquí sí, y si además cambió la versión de HA, se marca como
        posible breaking change del update.
        """
        if self._diff_done:
            return
        self._diff_done = True
        previo = self._snapshot or {}
        antes = previo.get("entries") or {}
        if not antes:
            return

        perdidas = []
        for entry_id, titulo in antes.items():
            config_entry = self.hass.config_entries.async_get_entry(entry_id)
            if config_entry is None:
                perdidas.append((titulo, "ya no existe"))
            elif entry_id not in sanos:
                estado = "no cargó" if config_entry.state is not ConfigEntryState.LOADED else "sin entidades vivas"
                perdidas.append((config_entry.title or titulo, estado))
        if not perdidas:
            return

        ha_antes = previo.get("ha_version") or "?"
        ha_ahora = getattr(self.hass.config, "version", None) or "?"
        cambio_version = ha_antes != ha_ahora
        detalle = ", ".join(f"{t} ({m})" for t, m in perdidas)
        _LOGGER.warning(
            "Tras el arranque no volvieron %s integraciones: %s%s",
            len(perdidas),
            detalle,
            f" — y HA cambió de {ha_antes} a {ha_ahora}" if cambio_version else "",
        )
        self.hass.bus.async_fire(
            EVENT_RESTART_DIFF,
            {
                "perdidas": [{"title": t, "motivo": m} for t, m in perdidas],
                "ha_antes": ha_antes,
                "ha_ahora": ha_ahora,
                "posible_breaking_change": cambio_version,
                "foto_de": previo.get("at"),
            },
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "restart_diff",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="restart_diff_update" if cambio_version else "restart_diff",
            translation_placeholders={
                "count": str(len(perdidas)),
                "entries": detalle,
                "ha_antes": ha_antes,
                "ha_ahora": ha_ahora,
            },
        )

    def _cadence_eligible(self, entity_id: str, state) -> bool:
        """Solo sensores numéricos periódicos: son los que tienen cadencia propia.

        Un binary_sensor de puerta puede estar meses sin cambiar y eso es sano;
        un sensor de potencia que se calla 5x su ritmo, no.
        """
        if not entity_id.startswith("sensor."):
            return False
        if state.attributes.get("state_class") != "measurement":
            return False
        if state.state in ("unavailable", "unknown"):
            return False
        return True

    def _learn_cadence(self, entity_id: str, reported: datetime) -> float | None:
        """Aprende cada cuánto reporta esta entidad. Devuelve la mediana en segundos.

        Ojo con la resolución: como se muestrea en cada escaneo, la cadencia
        aprendida nunca baja del intervalo de escaneo. No importa — lo que se
        busca es detectar SILENCIO, no medir la frecuencia exacta.
        """
        c = self._cadence.setdefault(entity_id, {"gaps": [], "last": None, "median": None})
        iso = reported.isoformat()
        if c["last"] == iso:
            return c["median"]
        if c["last"]:
            prev = dt_util.parse_datetime(c["last"])
            if prev:
                gap = (reported - prev).total_seconds()
                if 0 < gap < 86400:  # descartar saltos absurdos (reboots, relojes)
                    c["gaps"].append(gap)
                    del c["gaps"][:-CADENCE_SAMPLES]
        c["last"] = iso
        if len(c["gaps"]) >= CADENCE_MIN_SAMPLES:
            ordenados = sorted(c["gaps"])
            c["median"] = ordenados[len(ordenados) // 2]
        return c["median"]

    async def _scan_auto_stale(self, data: VeladorData) -> None:
        """Congelados sin lista manual: aprende la cadencia de cada sensor y avisa
        cuando uno se calla mucho más de lo suyo.

        Deliberadamente NO cura: es una heurística, y disparar reloads masivos
        desde una heurística haría más daño que el congelamiento. Reporta y ya —
        la lista manual de stale sigue siendo la que cura.
        """
        if not self._opt(CONF_AUTO_STALE, DEFAULT_AUTO_STALE):
            return
        manual = set(self._opt(CONF_STALE_ENTITIES, []))
        excluded = self._excluded_domains
        registry = er.async_get(self.hass)
        now = dt_util.utcnow()
        piso = AUTO_STALE_FLOOR_MINUTES * 60
        vistos: set[str] = set()

        for reg_entry in registry.entities.values():
            entity_id = reg_entry.entity_id
            if reg_entry.disabled_by or entity_id in manual:
                continue
            if (reg_entry.platform or "") in excluded:
                continue
            state = self.hass.states.get(entity_id)
            if state is None or not self._cadence_eligible(entity_id, state):
                continue
            vistos.add(entity_id)
            reported = getattr(state, "last_reported", None) or state.last_updated
            median = self._learn_cadence(entity_id, reported)
            if not median:
                continue  # aún aprendiendo
            umbral = max(median * AUTO_STALE_MULTIPLIER, piso)
            age = (now - reported).total_seconds()
            if age <= umbral:
                if entity_id in self._auto_stale_active:
                    self._auto_stale_active.discard(entity_id)
                    ir.async_delete_issue(self.hass, DOMAIN, f"autostale_{entity_id}")
                    _LOGGER.info("Volvió a reportar: %s", entity_id)
                continue

            info = {
                "entity_id": entity_id,
                "state": state.state,
                "minutes_stale": int(age // 60),
                "cadencia_normal_min": round(median / 60, 1),
                "auto": True,
            }
            data.stale.append(info)
            if entity_id in self._auto_stale_active:
                continue
            self._auto_stale_active.add(entity_id)
            _LOGGER.warning(
                "Sensor mudo (cadencia aprendida): %s lleva %s min sin reportar; "
                "lo normal en él son %s min",
                entity_id,
                info["minutes_stale"],
                info["cadencia_normal_min"],
            )
            self.hass.bus.async_fire(EVENT_AUTO_STALE, info)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"autostale_{entity_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="auto_stale",
                translation_placeholders={
                    "entity_id": entity_id,
                    "minutes": str(info["minutes_stale"]),
                    "cadence": str(info["cadencia_normal_min"]),
                },
            )

        # Olvidar entidades que ya no existen para que el Store no crezca solo.
        for entity_id in list(self._cadence):
            if entity_id not in vistos and entity_id not in manual:
                del self._cadence[entity_id]

    def _stale_recover(self, entity_id: str, issue_id: str, silent: bool) -> None:
        if entity_id in self._stale_active:
            self._stale_active.discard(entity_id)
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            if not silent:
                _LOGGER.info("Sensor descongelado: %s", entity_id)
                self.hass.bus.async_fire(EVENT_STALE_RECOVERED, {"entity_id": entity_id})

    def _on_zombie_detected(self, config_entry: ConfigEntry, info: dict) -> None:
        _LOGGER.warning(
            "Zombie detectado: %s (%s) — %s/%s entidades unavailable",
            config_entry.title,
            config_entry.domain,
            info["dead"],
            info["total"],
        )
        self.hass.bus.async_fire(EVENT_ZOMBIE_DETECTED, info)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"zombie_{config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="zombie",
            translation_placeholders={
                "title": config_entry.title,
                "domain": config_entry.domain,
                "dead": str(info["dead"]),
                "total": str(info["total"]),
            },
        )

    def _backoff_delta(self, attempts: int) -> timedelta:
        """Backoff exponencial con jitter; el último escalón es cooldown_hours."""
        steps = list(BACKOFF_MINUTES) + [
            self._opt(CONF_COOLDOWN_HOURS, DEFAULT_COOLDOWN_HOURS) * 60
        ]
        minutes = steps[min(attempts - 1, len(steps) - 1)]
        return timedelta(minutes=minutes * random.uniform(0.9, 1.15))

    def _count_dead(self, config_entry: ConfigEntry) -> tuple[int, int]:
        registry = er.async_get(self.hass)
        dead = 0
        total = 0
        for reg_entry in registry.entities.values():
            if (
                reg_entry.config_entry_id != config_entry.entry_id
                or reg_entry.disabled_by
            ):
                continue
            state = self.hass.states.get(reg_entry.entity_id)
            if state is None:
                continue
            total += 1
            if state.state == "unavailable":
                dead += 1
        return dead, total

    async def _probe_after_reload(self, entry_id: str) -> None:
        """Probe post-reload: cerrar el incidente a los 90s, no al siguiente scan."""
        config_entry = self.hass.config_entries.async_get_entry(entry_id)
        if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
            return
        watch = self._watch.get(entry_id)
        if watch is None or watch.strikes == 0:
            return  # ya resuelto por otra vía
        dead, total = self._count_dead(config_entry)
        if total == 0:
            return  # entidades aún levantando; que juzgue el próximo scan
        if (dead / total) >= self._opt(CONF_THRESHOLD, DEFAULT_THRESHOLD):
            return  # sigue muerto; el scan reintentará según backoff
        self._on_healed(config_entry, watch)
        watch.strikes = 0
        watch.incurable = False
        watch.zombie_since = None
        self._save_state()
        await self.async_request_refresh()

    async def _maybe_heal(
        self,
        config_entry: ConfigEntry,
        watch: WatchState,
        info: dict,
    ) -> None:
        if self._reauth_pending(config_entry.entry_id):
            if not watch.needs_reauth:
                watch.needs_reauth = True
                watch.reauth_since = dt_util.utcnow()
                _LOGGER.warning(
                    "%s (%s) tiene reauth pendiente: el reload no cura eso, "
                    "se requieren credenciales",
                    config_entry.title,
                    config_entry.domain,
                )
                self.hass.bus.async_fire(EVENT_REAUTH_NEEDED, info)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"reauth_{config_entry.entry_id}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="reauth",
                    translation_placeholders={
                        "title": config_entry.title,
                        "domain": config_entry.domain,
                    },
                )
            return

        if watch.flapping:
            # Estado inestable: el reload maquilla un problema físico
            # (corriente, cable, RF, pila). No quemar más curas.
            return

        now = dt_util.utcnow()

        if watch.incurable:
            # Half-open: un probe espaciado — muchos incurables de nube
            # sanan solos cuando el proveedor vuelve.
            if watch.last_reload and now - watch.last_reload < timedelta(
                hours=INCURABLE_RETRY_HOURS
            ):
                return
            _LOGGER.info(
                "Probe half-open a incurable %s (%s)",
                config_entry.title,
                config_entry.domain,
            )
        else:
            if watch.reload_attempts >= MAX_RELOAD_ATTEMPTS:
                # Agotó la escalera de backoff: incurable, pero NO terminal —
                # pasa a reintento espaciado 1×/24h (half-open).
                watch.incurable = True
                _LOGGER.error(
                    "Zombie incurable: %s (%s) — %s reloads sin efecto; "
                    "reintento espaciado 1×/%sh",
                    config_entry.title,
                    config_entry.domain,
                    watch.reload_attempts,
                    INCURABLE_RETRY_HOURS,
                )
                self.hass.bus.async_fire(EVENT_INCURABLE, info)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"zombie_{config_entry.entry_id}",
                    is_fixable=True,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="incurable",
                    translation_placeholders={
                        "title": config_entry.title,
                        "domain": config_entry.domain,
                        "attempts": str(watch.reload_attempts),
                    },
                )
                return
            if watch.reload_attempts and watch.last_reload:
                if now - watch.last_reload < self._backoff_delta(watch.reload_attempts):
                    return

        watch.last_reload = now
        watch.reload_attempts += 1
        _LOGGER.warning(
            "Reviviendo %s (%s), intento %s",
            config_entry.title,
            config_entry.domain,
            watch.reload_attempts,
        )
        # En tarea aparte: un reload lento no debe bloquear el escaneo.
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(config_entry.entry_id)
        )
        entry_id = config_entry.entry_id

        @callback
        def _schedule_probe(_now) -> None:
            self.hass.async_create_task(self._probe_after_reload(entry_id))

        async_call_later(self.hass, PROBE_DELAY_SECONDS, _schedule_probe)

    def _on_healed(self, config_entry: ConfigEntry, watch: WatchState) -> None:
        now = dt_util.utcnow()
        attempts_used = watch.reload_attempts
        downtime_min = (
            int((now - watch.zombie_since).total_seconds() // 60)
            if watch.zombie_since
            else None
        )
        watch.healed_count += 1
        watch.reload_attempts = 0
        watch.needs_reauth = False
        watch.reauth_since = None
        watch.heal_history = [
            t for t in watch.heal_history if now - t < timedelta(hours=FLAP_WINDOW_HOURS)
        ]
        watch.heal_history.append(now)
        ir.async_delete_issue(self.hass, DOMAIN, f"reauth_{config_entry.entry_id}")
        self._healed_total += 1
        _LOGGER.info(
            "Revivió: %s (%s) — downtime %s min, %s intento(s)",
            config_entry.title,
            config_entry.domain,
            downtime_min if downtime_min is not None else "?",
            attempts_used,
        )
        self.hass.bus.async_fire(
            EVENT_HEALED,
            {
                "entry_id": config_entry.entry_id,
                "domain": config_entry.domain,
                "title": config_entry.title,
                "downtime_min": downtime_min,
                "attempts_used": attempts_used,
            },
        )
        ir.async_delete_issue(self.hass, DOMAIN, f"zombie_{config_entry.entry_id}")

        if len(watch.heal_history) >= FLAP_MAX_HEALS and not watch.flapping:
            # Recae una y otra vez: el reload no es la cura, esto es físico.
            watch.flapping = True
            _LOGGER.warning(
                "FLAPPING: %s (%s) revivió %s veces en %sh — auto-heal "
                "suprimido, revisar corriente/cable/RF/pila",
                config_entry.title,
                config_entry.domain,
                len(watch.heal_history),
                FLAP_WINDOW_HOURS,
            )
            self.hass.bus.async_fire(
                EVENT_FLAPPING,
                {
                    "entry_id": config_entry.entry_id,
                    "domain": config_entry.domain,
                    "title": config_entry.title,
                    "heals_window": len(watch.heal_history),
                },
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"flapping_{config_entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="flapping",
                translation_placeholders={
                    "title": config_entry.title,
                    "domain": config_entry.domain,
                    "count": str(len(watch.heal_history)),
                    "hours": str(FLAP_WINDOW_HOURS),
                },
            )
