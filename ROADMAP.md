# ROADMAP — Velador

> **Estado: todas las features del roadmap original están liberadas (última: v0.9.0).**
> Lo que siga sale de uso real y de lo que pida la gente, no de esta lista.
>
> **La v1.0 se reserva a propósito.** Un 1.0 dice "estable y probado por gente que no soy yo":
> se marcará cuando esté en la tienda default de HACS y haya uso real de terceros. Hoy el
> proyecto tiene dos semanas, cero usuarios externos y el PR de la tienda en cola.

Velador detecta y cura la muerte silenciosa en Home Assistant: integraciones zombie, sensores congelados y todo lo que falla sin avisar. Lo que NO va a ser: notificador push, gestor de Zigbee, plataforma de métricas ni dashboard — la señal siempre será Repairs + entidades + eventos, con cero red propia y cero dependencias.

## La frontera (regla de producto)

El ecosistema ya tiene auditores; Velador no compite con ellos, los completa:

| Herramienta | Territorio | Pregunta que responde |
|---|---|---|
| **Watchman** | Config estática | "¿Tu YAML apunta a algo que no existe?" |
| **Spook** | Referencias rotas | "¿Hay fantasmas en tus automatizaciones/dashboards?" |
| **Retry nativo de HA** | Entries que no cargaron | "¿Reintento el setup que falló?" |
| **Velador** | **Estado real en runtime + acción** | "¿Lo que HA dice que está vivo, está vivo de verdad — y si no, lo revivo?" |

Toda feature nueva pasa este filtro: si es análisis estático de configuración, es de Watchman/Spook y se descarta; si es reintentar setups fallidos a secas, ya lo hace core; si es observar el estado real del sistema en operación y actuar sobre él, es de Velador.

---

## v0.3 — Cerrar los puntos ciegos que más duelen ✅ (liberada en v0.3.0/0.3.1)

**Canarios: entidades críticas que curan su entry sin esperar el 90%**
Lista opcional de entity_ids; si un canario lleva >N min `unavailable`, se resuelve su entry vía entity registry y entra a la escalera de heal aunque el ratio global no cruce el umbral. Caza la muerte PARCIAL: 1 CT muerto de 4 en Emporia jamás llega a 90%, y la casa origen reconstruyó este watchdog 3 veces en YAML antes de que existiera Velador.

**Conciencia de reauth: no quemar reloads en zombies que piden manos**
Antes de recargar, consultar `flow.async_progress()` filtrando `source == reauth` del mismo entry; si hay reauth pendiente, saltar los reloads y marcar `needs_reauth` con Repair propio y evento `velador_reauth_needed`. El patrón SmartThings/Bambu: el reload da 200 y no cura NUNCA — hoy Velador gasta 2 intentos y 12 horas de cooldown antes de decir lo que se sabía en el primer escaneo.

**Auto-heal para sensores congelados**
Cerrar el loop de v0.2: entidad stale → `config_entry_id` por registry → misma escalera reload/cooldown/incurable, compartiendo WatchState (varias stale del mismo entry = un solo reload). Obligatorio: veto a dominios hub (mqtt, zha) — recargar el bus entero de la casa por un sensor pasmado hace más daño que el congelamiento. Motivación: 3 horas de watchdogs ciegos tras el apagón del 22-jul por entidades congeladas con estado restaurado viejo.

**Canario de dependencia: no gastar curas sin internet**
Opción para señalar una entidad de conectividad (WAN, router); si está caída, se congelan strikes e intentos de las integraciones cloud — la falla es del entorno, no de la integración. Al recuperarse, scan inmediato con curación agresiva. Evita el falso-incurable documentado: post-apagón sin WAN, todo reload quemado en vano dejó 5 integraciones "incurables" ~20h.

**Este archivo + README honesto**
El README linkeaba a un ROADMAP.md que no existía (404 en la primera visita). Ya no.

---

## v0.4 — Curar mejor, no más ✅ (liberada: memoria en v0.4.0, resto en v0.5.0)

**Memoria persistente de WatchState (promovido desde v0.5)**
Persistir strikes, intentos, incurables y cooldowns en `Store` para que un restart no borre lo aprendido. Evidencia del update a HA 2026.8 (5-ago): tras el restart, los 2 incurables CONOCIDOS (smartthings con token vencido, bambu_lab pidiendo reauth) volvieron a "intento 1" — Velador re-quemará 2 reloads y 12h de cooldown en cada uno para re-descubrir lo que ya había diagnosticado. Con memoria, un incurable previo arranca en el circuit breaker espaciado, no desde cero. También cubre el reset por cambio de opciones (recarga del entry = amnesia hoy).

**Vigilar entries en SETUP_ERROR / SETUP_RETRY**
Hoy el escaneo hace `continue` en todo lo que no está LOADED, así que un entry caído en setup_error es invisible. Extender el loop con la misma escalera y la conciencia de reauth de v0.3 (el reload solo cuando puede curar). Escenario real: el Volvo XC90 cayó en setup_error con un micro-corte y nadie lo cubría; VeSync cayó en invalid_auth transitorio y un simple reload lo curó tras ~20h de zombie. En SETUP_RETRY, templanza: el retry nativo de HA ya corre.

**Circuit breaker: backoff exponencial + half-open (adiós cooldown plano)**
Tras el primer reload fallido el circuito abre con backoff (30 min → 2h → 6h, con jitter); en cada vencimiento, un reload de prueba. "Incurable" deja de ser terminal: pasa a reintento espaciado 1×/24h, porque muchos incurables de nube sanan solos cuando el proveedor vuelve. El caso eight_sleep: marcado incurable por una caída de nube de 3h que sanaba sola — hoy espera a que un humano vea el Repair días después.

**Modo tormenta: correlación de zombies masivos + curación escalonada**
Si ≥3 entries cruzan a zombie en la misma ventana, no son N fallas: es un apagón o caída de red. UN Repair agregado ("posible corte: 5 integraciones cayeron a las HH:MM"), evento `velador_storm_detected`, y reloads SECUENCIALES con delay — disparar 10 reloads simultáneos contra un router que acaba de rebootar produce exactamente el segundo strike falso. Cada apagón CFE de la casa origen tumbaba 5-8 integraciones a la vez.

**Estado "inestable": flapping y reincidencia son la misma señal**
Hoy `_on_healed` resetea los intentos en cada recuperación, así que el ciclo zombie→healed→zombie consume reloads infinitos y nunca converge. Ventana deslizante de transiciones en WatchState: muchas recaídas → suprimir auto-heal, Repair de "el reload no es la cura, esto es físico (corriente, cable, RF, pila)" y evento con el historial. El Hue Bridge con plug flojo estuvo semanas maquillado por curas que funcionaban 20 minutos.

**Probe post-reload con MTTR**
A los 90s del reload, recontar entidades del entry: si revivió, cerrar el incidente ya (no hasta 10 min después en el siguiente scan) y enriquecer `velador_healed` con downtime y intentos usados. Convierte "revivió" en métrica: Emporia sana en 40s, VeSync en 8 min — esa diferencia es diagnóstico.

---

## v0.5 — Señal más fina, superficie estándar ✅ (liberada en v0.5.0)

**Zombies a nivel device**
Agrupar entidades por `device_id` dentro de entries multi-device (mqtt, zha, hue, tuya): si el 100% de las entidades de un device llevan >X horas muertas → evento + Repair agregado con nombre y área. Sin auto-heal — un device no se recarga; es señal pura. Es el punto ciego matemático del ratio: 3 sensores muertos de 40 = 7%, integración "sana", y la luz del baño no prende.

**Radio de daño: automatizaciones ciegas en el Repair**
Al declarar zombie/stale, enumerar con `automations_with_entity()` (API de core, sin parsear YAML) las automatizaciones que dependen de las entidades muertas e incluirlas en el Repair y el evento. El daño real de un sensor muerto casi nunca es el sensor: el Aqara del armario murió después de prender el deshumidificador y la automatización de apagado nunca pudo disparar — el aparato corrió 2 días sin parar.

**Servicios `velador.heal` y `velador.audit`**
`heal` fuerza el ciclo sobre un entry reseteando strikes/cooldown (habilita "cuando vuelva la luz, cura todo" como automatización del usuario); `audit` con `supports_response` devuelve el dict completo de zombies/stale/incurables — consumible por scripts, el conversation agent y auditores externos sin parsear atributos.

**Repairs arreglables: botón "Revivir ahora"**
Hoy todos los issues nacen con `is_fixable=False` — puros letreros. Con `RepairsFlow`, el incurable trae botón: "ya reconecté la impresora → Arreglar" sin ir a Devices & Services. Es la mitad de la promesa "señal = Repairs" que faltaba.

**Reauth pendiente como entidad**
`sensor.velador_reauth_pendientes` con lista y antigüedad (persistida en Store — el flow no trae timestamp). El Repair nativo de HA se descarta con un clic y no vuelve; con entidad, el usuario construye SU señal (dashboard, LED, lo que quiera).

**Detección por eventos**
Listener barato de transiciones a `unavailable` que encola un chequeo dirigido del entry dueño con debounce de ~60s. Baja el peor caso de detección de ~15 min a ~1 min — tras un apagón, eso es la diferencia entre un hueco de datos y un blip. El scan de 5 min queda de red de seguridad y para stale.

**Contador persistente + diagnostics**
`Store` para `revividas_total` (la persistencia de WatchState se promovió a v0.4); curaciones por dominio y MTTR como atributos. Y `diagnostics.py` con la tabla de vigilancia completa (redactada): un issue de GitHub con JSON descargable en vez de ping-pong de logs.

---

## v0.6 ✅ / v0.7 ✅ (liberadas 11-ago-2026)

**v0.6 — Auto-stale por cadencia aprendida.** Aprende el ritmo propio de cada sensor numérico y avisa a >5x, con piso de 30 min. Opt-in y **sin auto-heal**: reportar desde una heurística sí, recargar en masa desde una heurística no.

**v0.7 — Diff post-arranque.** Foto del último estado sano; al volver de un reinicio dice qué no regresó, y si cambió la versión de HA lo marca como posible breaking change.

## Kit de arranque ✅ (liberado como v0.8.0 el 11-ago-2026)

**~~Auto-stale: congelados sin configurar lista~~ — LIBERADO en v0.6**
Modo automático (default on, con override manual): aprender la cadencia típica por entidad con `state_class: measurement` (mediana rodante de `last_reported`, ~24h) y declarar congelado a >5× su propia cadencia con piso de 30 min. Honestidad obligada: sensores push-on-change tienen cadencia irregular — la heurística reduce falsos positivos, no los elimina; documentarlo y dar opt-out claro. Es la diferencia entre "script útil para quien sabe" y "lo instalas y te cuida".

**~~Diff post-arranque: "el restart te rompió X"~~ — LIBERADO en v0.7**
Snapshot periódico en Store de disponibilidad por entry y por automatización; al terminar la gracia post-boot, comparar y levantar Repair con lista concreta de lo que estaba vivo y no volvió. Si cambió la versión de HA, etiquetar "posible breaking change del update" — el escenario del `kelvin`→`color_temp_kelvin` que rompió 7 automatizaciones en silencio.

**~~Distribución: brands + release + submission~~ — HECHO (íconos locales v0.3.1; piso 2024.8 en v0.9.1; PR hacs/default#9763 en cola)**
PR a `home-assistant/brands` (icon/logo 512×512), release taggeado, PR a `hacs/default`, y bump de `homeassistant` en hacs.json a 2024.8 (el código usa `last_reported`). Hoy instalar exige copiar una URL de custom repository — fricción que filtra al 95%.

**~~README que convierte + kit de arranque~~ — LIBERADO en v0.8.0**
Hero con screenshot del Repair, badges, y la tabla "¿por qué no basta X?" contra Watchman (audita refs, no revive), Spook (encuentra fantasmas, no cura) y el retry nativo de HA (no cubre loaded-pero-muerto) — esa tabla ES el pitch. Más: carpeta `blueprints/` ("Velador → avísame como TÚ quieras" con el notify que el usuario elija — la notificación es SU automatización, opt-in, cero-push intacto) y `lovelace/velador-dashboard.yaml` copy-paste con cards nativas: 90% del valor de una custom card con 5% del esfuerzo.

## v0.9 — Detector de olas sub-umbral ✅ (liberada 11-ago-2026)

Cerrar el último punto ciego que quedaba documentado: el transitorio masivo que se cura solo. Un hub que rebota 2 minutos tira 100+ entidades y se auto-recupera: nunca cruza el 90%×2 strikes, ningún canario aguanta 20 min, y Velador —correctamente— calla. Pero la RECURRENCIA de esas olas es señal de hardware enfermo (corriente floja, bridge moribundo) que hasta hoy solo se descubría por arqueología.

Implementado: ≥5 entidades del mismo entry (o la mitad, lo que sea mayor) cayendo en 90 s marcan una ola candidata; se confirma a los 10 min **solo si volvieron solas** — si siguen muertas nunca fue una ola, es un zombie y de eso ya se encarga la escalera. Se descartan las olas que pegan a varios entries a la vez (eso fue la casa, no el aparato) y las que ocurren con la WAN caída. Historial persistido en Store, porque la reincidencia se mide en semanas. Repair único al llegar a 3 olas en 7 días, evento por cada ola confirmada para quien quiera su contador, y `sensor.velador_olas_reincidentes`. Sin auto-heal: recargar no arregla una fuente floja.

Caso de origen: el Hue Bridge de la casa rebotó 4+ veces en el verano (jun, jul, 2×ago) y cada vez se diagnosticó a mano; la casa lo cubría con una automatización de contador que esto reemplaza.

---

## Ideas en evaluación (sin ola asignada)

Ninguna por ahora. El roadmap documentado está cerrado; lo que entre aquí sale de evidencia nueva, no de lluvia de ideas.

## Descartado a propósito

Ideas que pasaron por panel adversarial y murieron. No re-proponer sin evidencia nueva.

- **Vigilar SETUP_RETRY "a secas" (reload sin conciencia de reauth).** Duplica el retry nativo con backoff de HA, que ya corre indefinidamente, y quema intentos en tokens vencidos. La versión correcta es la de v0.4, con rama reauth.
- **Latido de automatizaciones (`last_triggered` vs horas esperadas).** Es healthchecks-para-automatizaciones: otro producto, con config manual por regla e intervalos esperados propensos a falso positivo. El radio de daño de v0.5 cubre la parte que sí es de Velador.
- **Línea base con recorder para auto-excluir crónicos.** La query de 7 días sobre todo el registry ahoga un HA Green con SQLite; "crónico" se aprende igual persistiendo las observaciones propias de Velador en Store, sin tocar recorder. El objetivo sobrevive; esa implementación no.
- **Bitácora completa de incidentes con MTBF/ofensores/external_statistics.** Es Grafana disfrazada — Velador cura, no hace postmortems. El contador persistente + diagnostics de v0.5 dan el 80% sin volverse plataforma de métricas.
- **Escaneo diario de triggers apuntando a entidades inexistentes.** Eso es Watchman, y Watchman ya existe. Velador solo reporta automatizaciones ciegas en el momento del incidente, donde el contexto es lo que nadie más da.
- **Custom card JS con botón "revivir".** Segundo repo de frontend para un proyecto de una persona. El YAML de cards nativas da el 90%; si algún día se justifica, será después de que exista `velador.heal` y lo pida gente real.
