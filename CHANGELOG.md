# Changelog

## 0.3.0 — 2026-08-04

- **Canarios por entidad:** lista de entidades críticas que, al llevar N min `unavailable`, curan su config entry directo — caza la muerte PARCIAL que el ratio 90% nunca ve (1 CT muerto de 4).
- **Conciencia de reauth:** si el entry tiene un reauth flow abierto, no se queman reloads (no curan credenciales); Repair `reauth` + evento `velador_reauth_needed`.
- **Auto-heal de congelados:** un sensor stale ahora dispara la escalera de curación de su entry dueño — con VETO a dominios hub (mqtt, zha, zwave_js, matter…): no se recarga el bus de la casa por un sensor pasmado.
- **Canario WAN:** entidad de conectividad opcional; sin internet se congela el juicio de integraciones cloud (la falla es del entorno) y al volver la WAN se liberan cooldowns para curación inmediata.


## 0.2.0 — 2026-08-04

- **Sensores congelados (stale):** nueva vigilancia de entidades que dejan de reportar sin ponerse `unavailable` — el sensor mentiroso que se queda pegado con el último valor. Lista de entidades y umbral configurables en Opciones. Usa `last_reported` (un valor repetido sano NO es stale). Detección + Repair + eventos; sin auto-heal en esta versión (ver ROADMAP).
- Nuevo `sensor.velador_congelados` + los congelados cuentan en `binary_sensor.velador_problema`.
- Eventos nuevos: `velador_stale_detected`, `velador_stale_recovered`.
- CI: se ignora el check de brands (pendiente PR a home-assistant/brands).

## 0.1.0 — 2026-08-04

- Primera versión: detección de integraciones zombie (config entry `loaded` con ≥90% de entidades `unavailable` × 2 escaneos, gracia post-boot), auto-heal con cooldown, escalado a incurable + Repairs, entidades, eventos y opciones de sensibilidad. es/en.
