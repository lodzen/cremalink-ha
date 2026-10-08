"""Shared fixtures for Cremalink tests.

Mock homeassistant at module level so imports work during collection.
Ported from delonghi-ha/tests/conftest.py's approach: stub HA modules with
MagicMock, then replace the specific bases config_flow.py/diagnostics.py
actually subclass or call with real, minimal stand-ins.
"""

import sys
from unittest.mock import MagicMock

_HA_MODULES = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers.selector",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.issue_registry",
    "homeassistant.data_entry_flow",
    "homeassistant.components",
    "homeassistant.components.diagnostics",
]


def _real_redact(data, keys_to_redact):
    """Stand-in for HA's async_redact_data — redacts top-level keys."""
    if not isinstance(data, dict):
        return data
    return {k: ("**REDACTED**" if k in keys_to_redact else v) for k, v in data.items()}


for mod_name in _HA_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

sys.modules["homeassistant.components.diagnostics"].async_redact_data = _real_redact


# Real ConfigFlow stub so config_flow.py's `class Foo(ConfigFlow, domain=...)`
# subclasses a real class instead of silently producing a MagicMock.
class _ConfigFlowBase:
    """Stand-in for HA's config_entries.ConfigFlow base."""

    def __init_subclass__(cls, **_kwargs) -> None:  # accept domain= kwarg
        super().__init_subclass__()

    async def async_set_unique_id(self, unique_id: str) -> None:
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        return None

    def async_create_entry(self, *, title: str, data: dict) -> dict:
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema=None,
        errors=None,
        description_placeholders=None,
    ) -> dict:
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders,
        }

    def async_show_menu(self, *, step_id: str, menu_options=None) -> dict:
        # Mirrors a real HA check: Home Assistant validates that a menu's
        # own step_id is a real async_step_* method (it re-checks this even
        # though menu *selections* route straight to async_step_<chosen>,
        # never back through this one) -- catches step-name typos/removals.
        if not hasattr(self, f"async_step_{step_id}"):
            raise AssertionError(
                f"async_show_menu(step_id={step_id!r}) has no matching "
                f"async_step_{step_id} method (Home Assistant requires it "
                "to exist even though it won't be called on selection)"
            )
        return {"type": "menu", "step_id": step_id, "menu_options": menu_options}

    def async_abort(self, *, reason: str) -> dict:
        return {"type": "abort", "reason": reason}


_ce_mod = sys.modules["homeassistant.config_entries"]
_ce_mod.ConfigFlow = _ConfigFlowBase


class _OptionsFlowBase(_ConfigFlowBase):
    """Stand-in for Home Assistant's OptionsFlow base."""


_ce_mod.OptionsFlow = _OptionsFlowBase

_ha_mod = sys.modules["homeassistant"]
_ha_mod.config_entries = _ce_mod
_ha_mod.const = sys.modules["homeassistant.const"]
_ha_mod.core = sys.modules["homeassistant.core"]
_ha_mod.exceptions = sys.modules["homeassistant.exceptions"]
_ha_mod.helpers = sys.modules["homeassistant.helpers"]
_ha_mod.components = sys.modules["homeassistant.components"]

_exc_mod = sys.modules["homeassistant.exceptions"]
_exc_mod.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
_exc_mod.HomeAssistantError = type("HomeAssistantError", (Exception,), {})

sys.modules["homeassistant.const"].Platform = MagicMock()


class _UpdateFailed(Exception):
    """Stand-in for HA's update_coordinator.UpdateFailed."""


class _DataUpdateCoordinatorBase:
    """Stand-in for HA's update_coordinator.DataUpdateCoordinator.

    Real enough for tests: stores state, and `async_config_entry_first_refresh`
    actually calls the subclass's `_async_update_data()` once.
    """

    def __init__(self, hass, logger, *, name, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()
        self.last_update_success = True

    async def async_request_refresh(self):
        return None


_uc_mod = sys.modules["homeassistant.helpers.update_coordinator"]
_uc_mod.DataUpdateCoordinator = _DataUpdateCoordinatorBase
_uc_mod.UpdateFailed = _UpdateFailed


class _CoordinatorEntityBase:
    """Stand-in for HA's update_coordinator.CoordinatorEntity."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = getattr(coordinator, "hass", None)

    @property
    def available(self):
        return getattr(self.coordinator, "last_update_success", True)

    def async_write_ha_state(self):
        return None

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        return None


_uc_mod.CoordinatorEntity = _CoordinatorEntityBase


class _RestoreEntity:
    """Stand-in for HA's restore_state.RestoreEntity (tests set ``_last_state``)."""

    _last_state = None

    async def async_get_last_state(self):
        return self._last_state


class _RestoreStateData:
    """Stand-in for HA's RestoreStateData; counts forced dumps."""

    dumps = 0

    @classmethod
    async def async_save_persistent_states(cls, hass):
        cls.dumps += 1


_restore_mod = type(sys)("homeassistant.helpers.restore_state")
_restore_mod.RestoreEntity = _RestoreEntity
_restore_mod.RestoreStateData = _RestoreStateData
sys.modules["homeassistant.helpers.restore_state"] = _restore_mod


class _EntityBase:
    """Minimal stand-in for HA's platform entity bases."""

    _attr_name = None
    _attr_unique_id = None
    _attr_icon = None
    _attr_device_info = None
    _attr_available = True
    _attr_entity_category = None
    _attr_translation_key = None
    _attr_entity_registry_enabled_default = True

    @property
    def entity_category(self):
        return self._attr_entity_category

    @property
    def translation_key(self):
        return self._attr_translation_key

    @property
    def entity_registry_enabled_default(self):
        return self._attr_entity_registry_enabled_default

    @property
    def name(self):
        return self._attr_name

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def device_info(self):
        return self._attr_device_info

    @property
    def available(self):
        return self._attr_available

    def async_write_ha_state(self):
        return None


for _platform_mod, _entity_attrs in (
    (
        "homeassistant.components.sensor",
        {"SensorEntity": type("SensorEntity", (_EntityBase,), {})},
    ),
    (
        "homeassistant.components.binary_sensor",
        {"BinarySensorEntity": type("BinarySensorEntity", (_EntityBase,), {})},
    ),
    (
        "homeassistant.components.select",
        {"SelectEntity": type("SelectEntity", (_EntityBase,), {})},
    ),
    (
        "homeassistant.components.button",
        {"ButtonEntity": type("ButtonEntity", (_EntityBase,), {})},
    ),
    (
        "homeassistant.components.switch",
        {"SwitchEntity": type("SwitchEntity", (_EntityBase,), {})},
    ),
):
    if _platform_mod not in sys.modules:
        sys.modules[_platform_mod] = MagicMock()
    for _name, _cls in _entity_attrs.items():
        setattr(sys.modules[_platform_mod], _name, _cls)


class _SensorDeviceClass:
    """Stand-in for HA's sensor.SensorDeviceClass enum."""

    ENUM = "enum"


sys.modules["homeassistant.components.sensor"].SensorDeviceClass = _SensorDeviceClass


class _BinarySensorDeviceClass:
    """Stand-in for HA's binary_sensor.BinarySensorDeviceClass enum."""

    RUNNING = "running"
    DOOR = "door"
    PROBLEM = "problem"


sys.modules[
    "homeassistant.components.binary_sensor"
].BinarySensorDeviceClass = _BinarySensorDeviceClass


if "homeassistant.helpers.entity" not in sys.modules:
    sys.modules["homeassistant.helpers.entity"] = MagicMock()


class _DeviceInfo(dict):
    """Stand-in for HA's helpers.entity.DeviceInfo (a TypedDict)."""


sys.modules["homeassistant.helpers.entity"].DeviceInfo = _DeviceInfo
sys.modules["homeassistant.helpers"].entity = sys.modules[
    "homeassistant.helpers.entity"
]

_const_mod = sys.modules["homeassistant.const"]
_const_mod.PERCENTAGE = "%"


class _UnitOfVolume:
    """Stand-in for HA's const.UnitOfVolume enum."""

    LITERS = "L"


_const_mod.UnitOfVolume = _UnitOfVolume


class _EntityCategory:
    """Stand-in for HA's const.EntityCategory enum."""

    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


_const_mod.EntityCategory = _EntityCategory


class _Platform:
    """Stand-in for HA's const.Platform enum."""

    SWITCH = "switch"
    BUTTON = "button"
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    SELECT = "select"


_const_mod.Platform = _Platform


class _IssueSeverity:
    """Stand-in for HA's issue_registry.IssueSeverity enum."""

    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


_ir_mod = sys.modules["homeassistant.helpers.issue_registry"]
_ir_mod.IssueSeverity = _IssueSeverity
_ir_mod.async_create_issue = MagicMock()
_ir_mod.async_delete_issue = MagicMock()
