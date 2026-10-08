"""Sensor platform for the Cremalink integration."""

from cremalink.ecam.statistics import CLOUD_COUNTER_CANDIDATES, STAT_LABELS
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTION_TYPE, CONNECTION_CLOUD, DOMAIN, STANDBY_STATUSES

#: Monitor-value sensors (diagnostic): (key, name, icon, unit, enum_profile_key).
#: Enum-keyed sensors expose translated states (T043/FR-033).
MONITOR_SENSORS = [
    ("status_name", "Status", "mdi:coffee-maker", None, "status"),
    ("progress_percent", "Progress", "mdi:progress-clock", PERCENTAGE, None),
    ("accessory_name", "Accessory", "mdi:cup", None, "accessory"),
    ("action_code", "Action Code", "mdi:state-machine", None, None),
]

#: Fields suppressed while the machine is in a standby-like status — the
#: machine stops evaluating them, so entities retain their last live value
#: instead (T044/FR-034).
_STANDBY_RETAINED_KEYS = {"progress_percent", "accessory_name", "action_code"}

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
    for key, name, icon, unit, enum_key in MONITOR_SENSORS:
        entities.append(
            CremalinkSensor(
                coordinator,
                entry,
                key,
                name,
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

    async_add_entities(entities)


class _CremalinkEntityBase(CoordinatorEntity):
    """Shared availability/lifecycle rules for Cremalink entities."""

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


class CremalinkSensor(_CremalinkEntityBase, SensorEntity):
    """Representation of a Cremalink monitor sensor (diagnostic)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key, name, icon, unit, options=None):
        """Initialize the sensor.

        Args:
            coordinator: The data update coordinator.
            entry: The config entry.
            key: The key to identify the sensor data.
            name: The name of the sensor.
            icon: The icon for the sensor.
            unit: The unit of measurement for the sensor.
            options: Enum state options for translated enum sensors.
        """
        super().__init__(coordinator, entry)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._standby_cache = None
        if options:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = options
            self._attr_translation_key = f"cremalink_{key}"

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


class CremalinkStatisticSensor(_CremalinkEntityBase, SensorEntity):
    """Native 0xA2 statistics sensor (LAN-only)."""

    def __init__(self, coordinator, entry, a2_id, label, unit):
        super().__init__(coordinator, entry)
        self._a2_id = a2_id
        self._attr_name = label.replace("_", " ").title()
        self._attr_unique_id = f"{entry.entry_id}_{_stat_suffix(a2_id, label)}"
        self._attr_icon = "mdi:counter"
        if unit == "l":
            self._attr_native_unit_of_measurement = UnitOfVolume.LITERS
            self._attr_icon = "mdi:water"

    @property
    def native_value(self):
        report = getattr(self.coordinator, "statistics", None)
        if report is None:
            return None
        entry = report.entries.get(self._a2_id)
        return entry.value if entry is not None else None


class CremalinkCloudCounterSensor(_CremalinkEntityBase, SensorEntity):
    """Cloud-counter statistics sensor backed by the Ayla datapoint cache."""

    def __init__(self, coordinator, entry, logical):
        super().__init__(coordinator, entry)
        self._logical = logical
        self._attr_name = logical.replace("_", " ").title()
        self._attr_unique_id = f"{entry.entry_id}_stat_{logical}"
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self):
        report = getattr(self.coordinator, "statistics", None)
        if report is None:
            return None
        return report.cloud_counters.get(self._logical)

    @property
    def extra_state_attributes(self):
        report = getattr(self.coordinator, "statistics", None)
        if report is None:
            return None
        breakdown = report.breakdowns.get(self._logical)
        return {"breakdown": breakdown} if breakdown else None
