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

STATUS_WATCHING = "vigilando"
STATUS_ZOMBIE = "zombie"
STATUS_HEALING = "reviviendo"
STATUS_INCURABLE = "incurable"
