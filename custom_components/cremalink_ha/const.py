"""Constants for the Cremalink Home Assistant integration."""

from homeassistant.helpers.entity import DeviceInfo

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


def catalog_ready_signal(entry_id: str) -> str:
    """Dispatcher signal: the cloud catalogue snapshot was seeded."""
    return f"{DOMAIN}_catalog_ready_{entry_id}"


def device_info(entry, device) -> DeviceInfo:
    """Shared device registry info — model comes from the device map.

    ``model_name`` is map data (``None`` when the map does not name the
    model); the firmware version is set separately via the device
    registry once ``firmware_info`` resolves.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="DeLonghi",
        model=getattr(device, "model_name", None),
    )


DEFAULT_LOCAL_SERVER_PORT = 10280
LOCAL_SERVER_PORT_FALLBACK_RANGE = 50
REPAIR_RECONFIGURE_REQUIRED = "reconfigure_required"

#: Statuses during which the machine stops evaluating alarm/switch/accessory
#: bytes — latched values must not surface as live readings (T044/FR-034).
STANDBY_STATUSES = {"in_standby", "going_to_sleep", "sleeping", "deep_sleep"}

#: Statuses in which the machine cannot start a drink (asleep or still waking).
NOT_READY_STATUSES = STANDBY_STATUSES | {"waking_up"}

#: Statuses in which the monitor's action byte does not mean "a drink is
#: being brewed": the standby family (the byte stays latched), waking up, and
#: the power-on/off rinse. Button availability must not follow it there.
NOT_BREWING_STATUSES = NOT_READY_STATUSES | {"rinsing"}

#: Device-map commands that have an entity translation (``cmd_<command>``).
#: Commands of custom maps fall back to a generated English name.
TRANSLATED_COMMANDS = frozenset(
    {
        "americano",
        "caffe_latte",
        "cappuccino",
        "cappuccino_mix",
        "cappuccino_plus",
        "coffee",
        "cortado",
        "doppio_plus",
        "double_espresso",
        "espresso",
        "espresso_macchiato",
        "espresso_soul",
        "flat_white",
        "hot_milk",
        "hot_water",
        "latte_macchiato",
        "long_coffee",
        "stop",
    }
)

#: Statuses in which the drink buttons are unavailable: asleep or waking up.
#: ``going_to_sleep`` is deliberately absent — the transition into standby
#: must not grey the buttons out, only reaching standby does.
BUTTON_UNAVAILABLE_STATUSES = (STANDBY_STATUSES - {"going_to_sleep"}) | {"waking_up"}
