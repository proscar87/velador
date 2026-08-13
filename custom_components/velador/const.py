"""Constantes de Velador."""

DOMAIN = "velador"

CONF_THRESHOLD = "threshold"
CONF_MIN_ENTITIES = "min_entities"
CONF_STRIKES = "strikes"
CONF_AUTO_HEAL = "auto_heal"
CONF_COOLDOWN_HOURS = "cooldown_hours"
CONF_EXCLUDE_DOMAINS = "exclude_domains"
CONF_GRACE_MINUTES = "grace_minutes"

DEFAULT_THRESHOLD = 0.9
DEFAULT_MIN_ENTITIES = 3
DEFAULT_STRIKES = 2
DEFAULT_AUTO_HEAL = True
DEFAULT_COOLDOWN_HOURS = 6
DEFAULT_GRACE_MINUTES = 15
DEFAULT_EXCLUDE_DOMAINS = ""

SCAN_INTERVAL_MINUTES = 5

# Dominios que nunca tiene sentido vigilar (helpers, la propia integración, etc.)
ALWAYS_IGNORED_DOMAINS = {
    "velador",
    "hacs",
    "mobile_app",
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_datetime",
    "template",
    "group",
    "schedule",
    "counter",
    "timer",
    "zone",
    "tag",
    "sun",
    "backup",
    "shopping_list",
}

CONF_CANARY_ENTITIES = "canary_entities"
CONF_CANARY_MINUTES = "canary_minutes"
DEFAULT_CANARY_MINUTES = 20
CONF_WAN_ENTITY = "wan_entity"

# Dominios hub: recargarlos por un sensor tira el bus entero de la casa.
HUB_DOMAINS_NO_RELOAD = {"mqtt", "zha", "zwave_js", "matter", "deconz", "otbr", "thread"}

CONF_STALE_ENTITIES = "stale_entities"
CONF_STALE_MINUTES = "stale_minutes"
DEFAULT_STALE_MINUTES = 60

EVENT_ZOMBIE_DETECTED = "velador_zombie_detected"
EVENT_HEALED = "velador_healed"
EVENT_INCURABLE = "velador_incurable"
EVENT_STALE_DETECTED = "velador_stale_detected"
EVENT_STALE_RECOVERED = "velador_stale_recovered"
EVENT_REAUTH_NEEDED = "velador_reauth_needed"
EVENT_STORM_DETECTED = "velador_storm_detected"
EVENT_FLAPPING = "velador_flapping"
EVENT_DEVICE_ZOMBIE = "velador_device_zombie"

# Modo tormenta: N zombies nuevos en el mismo escaneo = apagón/caída de red,
# no N fallas independientes. Un solo Repair + reloads secuenciales.
STORM_THRESHOLD = 3
STORM_RELOAD_SPACING_SECONDS = 30

# Circuit breaker: backoff entre reloads fallidos (el último escalón lo pone
# la opción cooldown_hours del usuario). Incurable deja de ser terminal:
# probe half-open 1×/24h.
BACKOFF_MINUTES = [30, 120]
INCURABLE_RETRY_HOURS = 24
MAX_RELOAD_ATTEMPTS = 3

# Probe post-reload: recontar entidades a los 90s para cerrar el incidente
# de inmediato (y medir downtime real) en vez de esperar el siguiente scan.
PROBE_DELAY_SECONDS = 90

# Flapping: zombie→sano→zombie en ciclo = problema físico, el reload maquilla.
FLAP_WINDOW_HOURS = 24
FLAP_MAX_HEALS = 3

# Detección por eventos: transición a unavailable → chequeo dirigido con debounce.
EVENT_DEBOUNCE_SECONDS = 60

# Zombies a nivel device (0 = apagado): 100% de las entidades de un device
# muertas > N horas. Señal pura, sin auto-heal (un device no se recarga).
CONF_DEVICE_ZOMBIE_HOURS = "device_zombie_hours"
DEFAULT_DEVICE_ZOMBIE_HOURS = 0

STATUS_WATCHING = "vigilando"
STATUS_ZOMBIE = "zombie"
STATUS_HEALING = "reviviendo"
STATUS_INCURABLE = "incurable"

# --- v0.6: auto-stale por cadencia aprendida ---
# Aprende cada cuánto reporta normalmente un sensor y avisa cuando se calla
# mucho más de lo suyo. Evita tener que mantener a mano la lista de stale.
CONF_AUTO_STALE = "auto_stale"
DEFAULT_AUTO_STALE = False          # opt-in: en casas con miles de entidades, primero mirar
AUTO_STALE_MULTIPLIER = 5           # se declara mudo a >5x su propia cadencia
AUTO_STALE_FLOOR_MINUTES = 30       # ...pero nunca antes de 30 min (piso anti-ruido)
CADENCE_SAMPLES = 12                # ventana de muestras por entidad
CADENCE_MIN_SAMPLES = 5             # antes de esto, no hay cadencia confiable
EVENT_AUTO_STALE = "velador_auto_stale_detected"

# --- v0.7: diff post-arranque ---
# Al reiniciar HA (o al actualizarlo) hay integraciones que ya no vuelven, y
# nadie avisa. Se guarda una foto de lo que estaba sano y se compara al arrancar.
EVENT_RESTART_DIFF = "velador_restart_diff"
SNAPSHOT_MIN_AGE_MINUTES = 20   # no fotografiar un arranque a medias

# --- v0.8: olas sub-umbral (transitorios masivos reincidentes) ---
# Un hub que rebota 2 minutos tira 100+ entidades y se recupera solo: nunca
# cruza el umbral zombie, ningún canario aguanta 20 min, y Velador —bien—
# calla. Pero la REINCIDENCIA de esas olas es hardware enfermo (corriente
# floja, bridge moribundo), y hoy eso solo se descubre por arqueología.
CONF_WAVE_DETECT = "wave_detect"
DEFAULT_WAVE_DETECT = True
WAVE_WINDOW_SECONDS = 90        # caídas dentro de esta ventana = la misma ola
WAVE_MIN_ENTITIES = 5           # ...y mínimo esto de entidades del mismo entry
WAVE_MIN_RATIO = 0.5            # ...o la mitad del entry, lo que resulte mayor
WAVE_CONFIRM_MINUTES = 10       # solo cuenta si se recuperó sola (si no, es zombie)
WAVE_HISTORY_DAYS = 7
WAVE_REPEAT_THRESHOLD = 3       # 3 olas en la ventana = "esto es físico"
EVENT_WAVE = "velador_wave"
EVENT_WAVE_RECURRENT = "velador_wave_recurrent"

# --- v0.10: la ola de nube no es la ola física ---
# Primera casa real con el detector puesto: cuatro integraciones de nube
# (growatt, emporia, starlink, tuya) hicieron entre 7 y 20 olas POR DÍA — su
# API se cae y vuelve, todo el día, y eso no lo arregla nadie mirando un cable.
# El conteo no las separa de un bridge moribundo; la densidad sí: lo físico
# hace una o dos olas en días sueltos. Arriba de este ritmo no hay Repair,
# solo se listan: el que grita siempre deja de leerse.
WAVE_CHRONIC_PER_DAY = 4.0        # olas/día promedio sobre lo observado
WAVE_CHRONIC_MIN_SPAN_DAYS = 1.0  # ...sostenido, no una racha de una noche
# Histéresis: el ritmo decae solo entre olas y salta con cada una, así que un
# entry rondando el umbral lo cruza en los dos sentidos varias veces por
# semana. Sin margen de salida, cada bajada re-levanta el Repair y grita "esto
# es físico" sobre una integración de nube — justo lo que esta ola vino a
# eliminar. Para dejar de ser crónica hay que bajar CLARO, no rozar.
WAVE_CHRONIC_EXIT_RATIO = 0.75
EVENT_WAVE_CHRONIC = "velador_wave_chronic"
