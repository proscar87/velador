"""Config flow de Velador."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.helpers import selector

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_AUTO_HEAL,
    CONF_AUTO_STALE,
    CONF_CANARY_ENTITIES,
    CONF_CANARY_MINUTES,
    CONF_DEVICE_ZOMBIE_HOURS,
    CONF_STALE_ENTITIES,
    CONF_STALE_MINUTES,
    CONF_WAN_ENTITY,
    CONF_WAVE_DETECT,
    DEFAULT_AUTO_STALE,
    DEFAULT_WAVE_DETECT,
    DEFAULT_CANARY_MINUTES,
    DEFAULT_DEVICE_ZOMBIE_HOURS,
    DEFAULT_STALE_MINUTES,
    CONF_COOLDOWN_HOURS,
    CONF_EXCLUDE_DOMAINS,
    CONF_GRACE_MINUTES,
    CONF_MIN_ENTITIES,
    CONF_STRIKES,
    CONF_THRESHOLD,
    DEFAULT_AUTO_HEAL,
    DEFAULT_COOLDOWN_HOURS,
    DEFAULT_EXCLUDE_DOMAINS,
    DEFAULT_GRACE_MINUTES,
    DEFAULT_MIN_ENTITIES,
    DEFAULT_STRIKES,
    DEFAULT_THRESHOLD,
    DOMAIN,
)


class VeladorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Alta de Velador: sin parámetros, los ajustes van en opciones."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Velador", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VeladorOptionsFlow:
        return VeladorOptionsFlow()


class VeladorOptionsFlow(OptionsFlow):
    """Ajustes de sensibilidad y auto-curación."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_THRESHOLD,
                    default=opts.get(CONF_THRESHOLD, DEFAULT_THRESHOLD),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1.0)),
                vol.Optional(
                    CONF_MIN_ENTITIES,
                    default=opts.get(CONF_MIN_ENTITIES, DEFAULT_MIN_ENTITIES),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
                vol.Optional(
                    CONF_STRIKES,
                    default=opts.get(CONF_STRIKES, DEFAULT_STRIKES),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                vol.Optional(
                    CONF_AUTO_HEAL,
                    default=opts.get(CONF_AUTO_HEAL, DEFAULT_AUTO_HEAL),
                ): bool,
                vol.Optional(
                    CONF_COOLDOWN_HOURS,
                    default=opts.get(CONF_COOLDOWN_HOURS, DEFAULT_COOLDOWN_HOURS),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=48)),
                vol.Optional(
                    CONF_GRACE_MINUTES,
                    default=opts.get(CONF_GRACE_MINUTES, DEFAULT_GRACE_MINUTES),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
                vol.Optional(
                    CONF_EXCLUDE_DOMAINS,
                    default=opts.get(CONF_EXCLUDE_DOMAINS, DEFAULT_EXCLUDE_DOMAINS),
                ): str,
                vol.Optional(
                    CONF_STALE_ENTITIES,
                    default=opts.get(CONF_STALE_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_STALE_MINUTES,
                    default=opts.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
                vol.Optional(
                    CONF_CANARY_ENTITIES,
                    default=opts.get(CONF_CANARY_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_CANARY_MINUTES,
                    default=opts.get(CONF_CANARY_MINUTES, DEFAULT_CANARY_MINUTES),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=240)),
                vol.Optional(
                    CONF_WAN_ENTITY,
                    description={"suggested_value": opts.get(CONF_WAN_ENTITY, "")},
                ): str,
                vol.Optional(
                    CONF_AUTO_STALE,
                    default=opts.get(CONF_AUTO_STALE, DEFAULT_AUTO_STALE),
                ): bool,
                vol.Optional(
                    CONF_DEVICE_ZOMBIE_HOURS,
                    default=opts.get(
                        CONF_DEVICE_ZOMBIE_HOURS, DEFAULT_DEVICE_ZOMBIE_HOURS
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=168)),
                vol.Optional(
                    CONF_WAVE_DETECT,
                    default=opts.get(CONF_WAVE_DETECT, DEFAULT_WAVE_DETECT),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
