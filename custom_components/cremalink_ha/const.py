"""Constants for the Cremalink Home Assistant integration."""

DEVICE_NAME = "device_name"

DOMAIN = "cremalink_ha"
CONF_ADDON_URL = "addon_url"
CONF_DSN = "dsn"
CONF_LAN_KEY = "lan_key"
CONF_DEVICE_IP = "device_ip"
CONF_DEVICE_MAP = "device_map"

CONF_CONNECTION_TYPE = "connection_type"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_FILE = "token_file"

# Cloud-assisted onboarding (cloud login replaces manual device-map/DSN entry)
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REGION = "region"
CONF_MANUAL_SETUP = "manual_setup"
DEFAULT_REGION = (
    "EU"  # only region with valid app credentials for v1 — see research.md #1
)

CONNECTION_LOCAL = "local"
CONNECTION_CLOUD = "cloud"

DEFAULT_ADDON_URL = "http://localhost:10280"
CUSTOM_MAP_DIR = "cremalink_custom_maps"
TOKEN_DIR = "cremalink_tokens"
DEFAULT_MONITOR_POLL_INTERVAL = 5
DEFAULT_NUDGER_POLL_INTERVAL = 1

# Embedded local server (spec: 002-embedded-local-server) — replaces the
# Supervisor add-on as the local connection mechanism.
CONF_CONNECTION_MODE = "connection_mode"
CONNECTION_MODE_EMBEDDED = "embedded"
CONF_ADVERTISED_IP = "advertised_ip"
DEFAULT_LOCAL_SERVER_PORT = 10280
LOCAL_SERVER_PORT_FALLBACK_RANGE = 50
REPAIR_RECONFIGURE_REQUIRED = "reconfigure_required"

#: Statuses during which the machine stops evaluating alarm/switch/accessory
#: bytes — latched values must not surface as live readings (T044/FR-034).
STANDBY_STATUSES = {"in_standby", "going_to_sleep", "sleeping", "deep_sleep"}

#: Statuses in which the machine cannot start a drink (asleep or still waking).
NOT_READY_STATUSES = STANDBY_STATUSES | {"waking_up"}
