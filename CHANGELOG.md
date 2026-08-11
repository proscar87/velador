# Changelog

## 0.9.0 — 2026-08-11

- **Olas reincidentes.** Un hub que rebota dos minutos tira 100+ entidades y se recupera solo:
  no cruza ningún umbral, ningún canario aguanta tanto, y Velador —con razón— se calla. Pero
  que eso pase **tres veces en una semana** ya no es un susto, es un aparato enfermo (fuente
  floja, bridge muriéndose), y hasta hoy eso solo se descubría haciendo arqueología de logs.
- Se cuenta, no se grita: ≥5 entidades del mismo entry (o la mitad, lo que sea mayor) cayendo
  en 90 s se marcan como ola **candidata**; a los 10 min se confirma solo si volvieron solas.
  Si no volvieron nunca fue una ola — es un zombie, y de eso ya se encarga la escalera de cura.
- Una ola que pega a **varias** integraciones a la vez se descarta: eso fue la casa (apagón,
  switch, wifi), no el aparato. Con la WAN caída tampoco se cuenta nada.
- Señal: un solo Repair al reincidir, evento `velador_wave` por cada ola confirmada (para quien
  quiera su propio contador), `velador_wave_recurrent` al cruzar el umbral, y
  `sensor.velador_olas_reincidentes`. **Sin auto-heal** — recargar no arregla una fuente floja.
- El historial se persiste: la reincidencia se mide en semanas y sin memoria cada reinicio
  perdonaría al aparato enfermo.
- Opción `wave_detect` (encendida por defecto).

## 0.8.0 — 2026-08-11

El kit de arranque: Velador pasa de "script útil para quien sabe" a integración que se instala
y cuida sola. Cierra las features que el roadmap listaba bajo "v1.0" — pero **la versión 1.0
se reserva** para cuando esté en la tienda default de HACS y con uso real de terceros, que es
lo que de verdad justifica ese número.

- **Blueprint de notificación** (`blueprints/automation/velador/notificacion.yaml`): Velador
  sigue sin mandar push por diseño, pero ahora hay un puente opcional donde **tú** eliges el
  servicio y qué eventos merecen interrumpirte. Recomendación incluida: empezar solo con
  *incurable* y *tormenta*, que son los que piden manos.
- **Dashboard copy-paste** (`lovelace/velador-dashboard.yaml`): tarjeta de estado que cambia
  según haya problema o no, vistazo de contadores, botones para `heal` y `audit`, e historial
  de 24 h. **Solo tarjetas nativas**, cero dependencias de HACS.
- **README reescrito**: la tabla "¿por qué no basta Watchman/Spook/el retry de core?" ahora es
  lo primero que se ve, porque ES el argumento del proyecto. Más badges, entidades, servicios
  y la sección de por qué existe — cada feature con la cicatriz que la originó.

## 0.7.0 — 2026-08-11

- **Diff post-arranque — "el restart te rompió X".** Velador guarda una foto de qué integraciones estaban sanas y, al volver de un reinicio, avisa cuáles no regresaron. Si además cambió la versión de Home Assistant, lo marca como **posible breaking change del update** y lo dice en el Repair. Era el hueco que quedaba: un entry que falla en silencio tras un reboot se ve igual que uno que nunca estuvo.
- La foto solo se toma cuando HA lleva ≥20 min arriba, para no retratar un arranque a medias y producir un diff falso.
- Evento nuevo: `velador_restart_diff` con la lista, ambas versiones de HA y la bandera de breaking change.

## 0.6.0 — 2026-08-11

- **Auto-stale por cadencia aprendida.** Detecta sensores congelados **sin lista manual**: aprende cada cuánto reporta normalmente cada sensor numérico (`state_class: measurement`) y avisa cuando se calla más de 5× su propio ritmo, con piso de 30 min. La cadencia aprendida se persiste, así que sobrevive reinicios.
- **Deliberadamente no cura**: es una heurística, y disparar reloads masivos desde una heurística haría más daño que el congelamiento. Reporta con Repair + evento `velador_auto_stale_detected`; la lista manual de stale sigue siendo la que cura.
- **Opt-in** (`auto_stale`, apagado por defecto): en casas con miles de entidades conviene mirar antes de encender.
- Las entidades que desaparecen se olvidan solas para que el almacenamiento no crezca sin control.

## 0.5.1 — 2026-08-07

- Fix hassfest: un issue no puede tener  y  a la vez — el botón "Revivir ahora" del incurable ahora usa solo strings de fix_flow (fix aportado desde la sesión hermana).

## 0.5.0 — 2026-08-06

Completa las olas v0.4 ("curar mejor, no más") y v0.5 ("señal más fina, superficie estándar") del ROADMAP.

**Curar mejor (v0.4):**
- **Modo tormenta:** ≥3 zombies nuevos en el mismo escaneo = apagón/caída de red, no N fallas — UN Repair agregado, evento `velador_storm_detected`, y reloads SECUENCIALES espaciados 30s (10 reloads simultáneos contra un router recién booteado producen el segundo strike falso).
- **Circuit breaker:** backoff exponencial con jitter entre reloads (30min → 2h → cooldown_hours como último escalón) e "incurable" deja de ser terminal: probe half-open 1×/24h — muchos incurables de nube sanan solos cuando el proveedor vuelve.
- **Flapping:** ≥3 revividas en 24h = inestable — el reload maquilla un problema físico (corriente/cable/RF/pila). Auto-heal suprimido + Repair + evento `velador_flapping`; se libera solo al estabilizarse.
- **SETUP_ERROR vigilado:** entries que no cargaron entran a la misma escalera (con conciencia de reauth). En SETUP_RETRY, templanza: el retry nativo ya corre.
- **Probe post-reload con MTTR:** a los 90s se recuenta el entry; si revivió, el incidente cierra YA y `velador_healed` trae `downtime_min` + `attempts_used`.

**Señal más fina (v0.5):**
- **Zombies a nivel device** (opcional, `device_zombie_hours` — 0 = apagado): devices con TODAS sus entidades muertas > N horas → Repair agregado con nombre y área + evento `velador_device_zombie`. El punto ciego matemático del ratio (3 de 40 = 7% = "sana").
- **Radio de daño:** cada zombie/stale enumera las `automations_ciegas` que dependen de sus entidades muertas (vía `automations_with_entity`, sin parsear YAML) — en evento y atributos.
- **Servicios `velador.heal` y `velador.audit`:** heal fuerza el ciclo (resetea strikes/cooldowns/incurable/flapping y recarga; sin entry_id cura todo lo enfermo — habilita "volvió la luz → cura todo"); audit regresa el dict completo con `supports_response`.
- **Repairs arreglables:** el incurable trae botón **"Revivir ahora"** (RepairsFlow) — arreglaste la causa física, un clic y listo.
- **`sensor.velador_reauth_pendientes`:** reauth como entidad con antigüedad (el Repair nativo se descarta con un clic y no vuelve).
- **Detección por eventos:** transición a `unavailable` → chequeo con debounce 60s. El peor caso baja de ~15 min a ~1-6 min; el scan de 5 min queda de red de seguridad.
- **`diagnostics.py`:** tabla de vigilancia completa descargable para issues de GitHub.

## 0.4.0 — 2026-08-06

- **Memoria persistente (Store):** strikes, intentos de reload, incurables, reauth pendiente, cooldowns y el contador de revividas sobreviven restarts de HA y recargas del entry (cambiar Opciones ya no borra lo aprendido). Un incurable conocido despierta como incurable — ya no re-quema 2 reloads + cooldowns para re-descubrir su diagnóstico. Motivación: el update a HA 2026.8 (5-ago) reseteó la memoria y los 2 incurables conocidos de la casa origen volvieron a "intento 1".
- **Repairs re-creados al arrancar:** los issues de incurable/reauth no sobreviven restarts en HA; ahora se re-emiten al restaurar la memoria para que la señal nunca quede muda.
- Guardado con dirty-check y delay (no muele la flash: solo escribe cuando algo cambió).
- Entries que ya no existen se descartan de la memoria al cargar.

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
