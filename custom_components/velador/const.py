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

EVENT_ZOMBIE_DETECTED = "velador_zombie_detected"
EVENT_HEALED = "velador_healed"
EVENT_INCURABLE = "velador_incurable"

STATUS_WATCHING = "vigilando"
STATUS_ZOMBIE = "zombie"
STATUS_HEALING = "reviviendo"
STATUS_INCURABLE = "incurable"
