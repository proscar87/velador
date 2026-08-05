"""Coordinator de Velador: detecta y revive integraciones zombie.

Un zombie es un config entry en estado LOADED cuyas entidades están
mayoritariamente unavailable — Home Assistant lo reporta como sano y no
hay nada nativo que lo detecte. Patrón observado tras apagones, restarts
y caídas de nube: la integración "carga" pero queda muerta por dentro.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import (
    ALWAYS_IGNORED_DOMAINS,
    CONF_CANARY_ENTITIES,
    CONF_CANARY_MINUTES,
    CONF_STALE_ENTITIES,
    CONF_STALE_MINUTES,
    CONF_WAN_ENTITY,
    DEFAULT_CANARY_MINUTES,
    EVENT_REAUTH_NEEDED,
    HUB_DOMAINS_NO_RELOAD,
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
    STATUS_HEALING,
    STATUS_INCURABLE,
    STATUS_ZOMBIE,
)

_LOGGER = logging.getLogger(__name__)


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


@dataclass
class VeladorData:
    """Resultado de un escaneo."""

    zombies: list[dict] = field(default_factory=list)
    incurables: list[dict] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)
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

        for config_entry in self.hass.config_entries.async_entries():
            if config_entry.domain in excluded:
                continue
            if config_entry.state is not ConfigEntryState.LOADED:
                continue

            ents = entities_by_entry.get(config_entry.entry_id, [])
            total = 0
            dead = 0
            dead_examples: list[str] = []
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
            watch = self._watch.setdefault(config_entry.entry_id, WatchState())
            is_zombie = (dead / total) >= threshold

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
            }

            if watch.incurable:
                data.incurables.append(info)
                continue

            data.zombies.append(info)

            if watch.strikes == strikes_needed:
                self._on_zombie_detected(config_entry, info)

            if auto_heal:
                await self._maybe_heal(config_entry, watch, cooldown, info)

        # Limpiar entries que ya no existen.
        for entry_id in list(self._watch):
            if entry_id not in seen_entry_ids:
                del self._watch[entry_id]
                ir.async_delete_issue(self.hass, DOMAIN, f"zombie_{entry_id}")

        await self._scan_canaries(data, wan_down)
        await self._scan_stale(data, wan_down)
        data.healed_total = self._healed_total
        return data

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
        if watch.incurable:
            return
        cooldown = timedelta(hours=self._opt(CONF_COOLDOWN_HOURS, DEFAULT_COOLDOWN_HOURS))
        full_info = {
            "entry_id": entry_id,
            "domain": config_entry.domain,
            "title": config_entry.title,
            **info,
        }
        await self._maybe_heal(config_entry, watch, cooldown, full_info)

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

    async def _maybe_heal(
        self,
        config_entry: ConfigEntry,
        watch: WatchState,
        cooldown: timedelta,
        info: dict,
    ) -> None:
        if self._reauth_pending(config_entry.entry_id):
            if not watch.needs_reauth:
                watch.needs_reauth = True
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

        now = dt_util.utcnow()
        if watch.last_reload and now - watch.last_reload < cooldown:
            return
        if watch.reload_attempts >= 2:
            # Dos reloads sin revivir = no se cura con reload (token vencido,
            # reauth pendiente, hardware muerto). Dejar de martillar.
            watch.incurable = True
            _LOGGER.error(
                "Zombie incurable: %s (%s) — %s reloads sin efecto, requiere manos",
                config_entry.title,
                config_entry.domain,
                watch.reload_attempts,
            )
            self.hass.bus.async_fire(EVENT_INCURABLE, info)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"zombie_{config_entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="incurable",
                translation_placeholders={
                    "title": config_entry.title,
                    "domain": config_entry.domain,
                    "attempts": str(watch.reload_attempts),
                },
            )
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

    def _on_healed(self, config_entry: ConfigEntry, watch: WatchState) -> None:
        watch.healed_count += 1
        watch.reload_attempts = 0
        watch.needs_reauth = False
        ir.async_delete_issue(self.hass, DOMAIN, f"reauth_{config_entry.entry_id}")
        self._healed_total += 1
        _LOGGER.info("Revivió: %s (%s)", config_entry.title, config_entry.domain)
        self.hass.bus.async_fire(
            EVENT_HEALED,
            {
                "entry_id": config_entry.entry_id,
                "domain": config_entry.domain,
                "title": config_entry.title,
            },
        )
        ir.async_delete_issue(self.hass, DOMAIN, f"zombie_{config_entry.entry_id}")
