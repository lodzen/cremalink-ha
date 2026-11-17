"""Sensor platform for the Cremalink integration."""

import logging

from cremalink.ecam.statistics import CLOUD_COUNTER_CANDIDATES, STAT_LABELS
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfVolume
from homeassistant.const import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTION_TYPE, CONNECTION_CLOUD, DOMAIN, STANDBY_STATUSES
from .coordinator import CremalinkCoordinator

_LOGGER = logging.getLogger(__name__)

#: Monitor-value sensors: (key, icon, unit, enum_profile_key). Names come from
#: the entity translations (``cremalink_<key>``); enum-keyed sensors also
#: expose translated states (T043/FR-033).
MONITOR_SENSORS = [
    ("status_name", "mdi:coffee-maker", None, "status"),
    ("progress_percent", "mdi:progress-clock", PERCENTAGE, None),
    ("accessory_name", "mdi:cup", None, "accessory"),
]

#: Fields suppressed while the machine is in a standby-like status — the
#: machine stops evaluating them, so entities retain their last live value
#: instead (T044/FR-034).
_STANDBY_RETAINED_KEYS = {"progress_percent", "accessory_name"}

#: Cloud "counters" that are state readings, not lifetime counters.
_NON_COUNTER_LOGICAL = {"descale_status", "water_hardness"}

#: A2-id → unique-id suffix overrides; everything else is stat_<label>.
_STAT_SUFFIX_OVERRIDES = {
    105: "stat_descales",
    106: "stat_water_total",
    108: "stat_filters",
    115: "stat_milk_cleans",
    43010: "stat_total_beverages",
}


def _stat_suffix(a2_id: int, label: str) -> str:
    """Stable unique-id suffix for a native statistics sensor."""
    if a2_id in _STAT_SUFFIX_OVERRIDES:
        return _STAT_SUFFIX_OVERRIDES[a2_id]
    if 3000 <= a2_id < 4000:
        return f"stat_bev_{label}"
    return f"stat_{label}"


def _device_info(entry):
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="cremalink",
    )


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry.
        async_add_entities: Function to add entities.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device = data["device"]
    connection_type = entry.data.get(CONF_CONNECTION_TYPE)

    entities = []
    enums = getattr(getattr(device, "monitor_profile", None), "enums", {}) or {}
    for key, icon, unit, enum_key in MONITOR_SENSORS:
        entities.append(
            CremalinkSensor(
                coordinator,
                entry,
                key,
                icon,
                unit,
                options=sorted(set(enums.get(enum_key, {}).values())) or None,
            )
        )

    # Statistics sensors are gated by the map's statistics_source and the
    # entry's connection type (contracts/ha-entities.md): native maps are
    # LAN-only, cloud_counters maps only make sense on cloud entries.
    statistics_source = getattr(device, "statistics_source", "native")
    if statistics_source == "native" and connection_type != CONNECTION_CLOUD:
        for a2_id, (label, unit) in sorted(STAT_LABELS.items()):
            entities.append(
                CremalinkStatisticSensor(coordinator, entry, a2_id, label, unit)
            )
    elif statistics_source == "cloud_counters" and connection_type == CONNECTION_CLOUD:
        # Counters with no candidate datapoint on this map produce no entity.
        map_names = set(getattr(device, "statistics_datapoints", None) or [])
        for logical, candidates in CLOUD_COUNTER_CANDIDATES.items():
            if map_names and not any(c in map_names for c in candidates):
                continue
            entities.append(CremalinkCloudCounterSensor(coordinator, entry, logical))

    if callable(getattr(device, "firmware_info", None)):
        entities.append(CremalinkFirmwareSensor(device, entry))

    async_add_entities(entities)


class _CremalinkEntityBase(CoordinatorEntity[CremalinkCoordinator]):
    """Shared availability/lifecycle rules for Cremalink entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._connection_type = entry.data.get(CONF_CONNECTION_TYPE)
        self._attr_device_info = _device_info(entry)

    @property
    def available(self):
        """Unavailable only after the consecutive-failure threshold (T045)."""
        if not self.coordinator.data:
            return False
        if self.coordinator.consecutive_failures >= self.coordinator.failure_threshold:
            return False
        return super().available


class CremalinkSensor(_CremalinkEntityBase, SensorEntity, RestoreEntity):
    """Representation of a Cremalink monitor sensor."""

    def __init__(self, coordinator, entry, key, icon, unit, options=None):
        """Initialize the sensor.

        Args:
            coordinator: The data update coordinator.
            entry: The config entry.
            key: The key to identify the sensor data.
            icon: The icon for the sensor.
            unit: The unit of measurement for the sensor.
            options: Enum state options for translated enum sensors.
        """
        super().__init__(coordinator, entry)
        self._key = key
        self._attr_translation_key = f"cremalink_{key}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._standby_cache = None
        self._restored = None
        if options:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = options

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        # Standby frames don't evaluate accessory/progress — seed the
        # standby cache so the last live reading survives a restart (US7).
        # The saved state is often "unknown" (standby already hid the
        # value when it was persisted) — fall back to last_known_value.
        last = await self.async_get_last_state()
        if last is None:
            return
        state = last.state
        if state in ("unknown", "unavailable"):
            state = last.attributes.get("last_known_value")
        if state is None or state in ("unknown", "unavailable"):
            return
        options = getattr(self, "_attr_options", None)
        if options is not None and state not in options:
            return
        try:
            value = float(state)
            self._restored = int(value) if value.is_integer() else value
        except (ValueError, TypeError):
            self._restored = state
        self._standby_cache = self._restored

    @property
    def extra_state_attributes(self):
        """Persist the last live reading — it survives "unknown" states.

        ``_standby_cache`` is updated on every successful read, so this
        attribute carries the newest confirmed value even while the
        visible state is unknown (standby frames without the field).
        """
        if self._standby_cache is None:
            return None
        return {"last_known_value": self._standby_cache}

    def _machine_in_standby(self):
        status = getattr(self.coordinator.data, "status_name", None)
        return status in STANDBY_STATUSES if status else False

    @property
    def native_value(self):
        """Return the value of the sensor."""
        value = getattr(self.coordinator.data, self._key, None)
        if self._key in _STANDBY_RETAINED_KEYS and self._machine_in_standby():
            # The machine stops evaluating accessory/progress in standby —
            # keep the last live reading instead of reporting stale bytes.
            return self._standby_cache
        if value is not None:
            self._standby_cache = value
            return value
        return self._restored


class _StatisticsSensorBase(_CremalinkEntityBase, RestoreEntity):
    """Retention rule for lifetime statistics counters.

    A counter's last read is never wrong — it can only change while the
    machine brews, i.e. when fetches succeed anyway. So an outage (dead
    machine, unreachable LAN) must not flap the entity to ``unavailable``:
    once a report exists its last values keep showing (FR-035 retention,
    extended to availability). ``RestoreEntity`` extends the same rule
    across restarts: standby blocks re-reads, so the last recorded state
    stays visible until a fresh report lands.
    """

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._restored = None
        #: Last real reading — seeds from _restored, then follows every
        #: report that carries the counter. A report missing the entry
        #: (the machine drops an id while rewriting its table after a
        #: brew) must not flap the value back to the startup state.
        self._last_value = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in ("unknown", "unavailable"):
            return
        try:
            value = float(last.state)
            self._restored = int(value) if value.is_integer() else value
        except ValueError:
            self._restored = last.state  # e.g. descale_status text readings
        self._last_value = self._restored

    @property
    def available(self):
        if self.coordinator.statistics is not None:
            return True
        return super().available


class CremalinkStatisticSensor(_StatisticsSensorBase, SensorEntity):
    """Native 0xA2 statistics sensor (LAN-only)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, entry, a2_id, label, unit):
        super().__init__(coordinator, entry)
        self._a2_id = a2_id
        self._attr_translation_key = f"stat_{label}"
        self._attr_unique_id = f"{entry.entry_id}_{_stat_suffix(a2_id, label)}"
        self._attr_icon = "mdi:counter"
        if unit == "l":
            self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
            self._attr_icon = "mdi:water"

    @property
    def native_value(self):
        report = getattr(self.coordinator, "statistics", None)
        if report is None:
            return self._last_value
        entry = report.entries.get(self._a2_id)
        if entry is not None:
            self._last_value = entry.value
        return self._last_value


class CremalinkCloudCounterSensor(_StatisticsSensorBase, SensorEntity):
    """Cloud-counter statistics sensor backed by the Ayla datapoint cache."""

    def __init__(self, coordinator, entry, logical):
        super().__init__(coordinator, entry)
        self._logical = logical
        self._attr_translation_key = f"stat_{logical}"
        self._attr_state_class = (
            None
            if logical in _NON_COUNTER_LOGICAL
            else SensorStateClass.TOTAL_INCREASING
        )
        self._attr_unique_id = f"{entry.entry_id}_stat_{logical}"
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self):
        report = getattr(self.coordinator, "statistics", None)
        if report is None:
            return self._last_value
        value = report.cloud_counters.get(self._logical)
        if value is not None:
            self._last_value = value
        return self._last_value

    @property
    def extra_state_attributes(self):
        report = getattr(self.coordinator, "statistics", None)
        if report is None:
            return None
        breakdown = report.breakdowns.get(self._logical)
        return {"breakdown": breakdown} if breakdown else None


class CremalinkFirmwareSensor(SensorEntity):
    """Wi-Fi module firmware; also puts the machine firmware on the device.

    Read once when added (cloud metadata, nothing is sent to the machine).
    A changed value after a restart shows that the cloud updated the
    firmware; the cloud does not announce pending updates.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "firmware_wifi_module"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"
    _attr_should_poll = False

    def __init__(self, device, entry):
        self.device = device
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_firmware_wifi_module"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        try:
            info = await self.hass.async_add_executor_job(self.device.firmware_info)
        except (OSError, ValueError, RuntimeError) as err:
            _LOGGER.debug("firmware info not readable: %s", err)
            return
        self._attr_native_value = info.get("wifi_module")
        attrs = {}
        if info.get("wifi_module_updated_at"):
            attrs["updated_at"] = info["wifi_module_updated_at"]
        if info.get("machine"):
            attrs["machine_firmware"] = info["machine"]
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()
        if info.get("machine"):
            registry = dr.async_get(self.hass)
            identifier = (DOMAIN, self._entry_id)
            if hasattr(registry, "async_get_device_by_identifier"):
                entry = registry.async_get_device_by_identifier(
                    identifier, self._entry_id
                )
            else:  # Home Assistant before 2026.11
                entry = registry.async_get_device(identifiers={identifier})
            if entry is not None and entry.sw_version != info["machine"]:
                registry.async_update_device(entry.id, sw_version=info["machine"])
