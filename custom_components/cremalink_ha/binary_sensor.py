"""Binary sensor platform for the Cremalink integration."""

from cremalink.ecam.monitor_bits import ALARM_BITS, SWITCH_BITS
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTION_TYPE, DOMAIN, STANDBY_STATUSES

BINARY_SENSORS = [
    ("is_busy", "Busy", None, BinarySensorDeviceClass.RUNNING),
    ("is_idle", "Idle", "mdi:sleep", None),
    (
        "is_watertank_open",
        "Water Tank Open",
        "mdi:water-boiler-alert",
        BinarySensorDeviceClass.DOOR,
    ),
    (
        "is_watertank_empty",
        "Water Tank Empty",
        "mdi:water-off",
        BinarySensorDeviceClass.PROBLEM,
    ),
    (
        "is_waste_container_full",
        "Waste Container Full",
        "mdi:delete-alert",
        BinarySensorDeviceClass.PROBLEM,
    ),
    (
        "is_waste_container_missing",
        "Waste Container Missing",
        "mdi:delete-alert",
        BinarySensorDeviceClass.PROBLEM,
    ),
]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the binary sensor platform.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry.
        async_add_entities: Function to add entities.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    entities = []
    for key, name, icon, dev_class in BINARY_SENSORS:
        entities.append(
            CremalinkBinarySensor(coordinator, entry, key, name, icon, dev_class)
        )

    # Every other documented monitor bit: motor position, clean knob, doors,
    # hardware faults… Rare faults are registered but disabled by default.
    for bit in SWITCH_BITS.values():
        entities.append(
            CremalinkBitSensor(
                coordinator, entry, "switch", bit, "mdi:toggle-switch-outline", None
            )
        )
    for bit in ALARM_BITS.values():
        entities.append(
            CremalinkBitSensor(
                coordinator,
                entry,
                "alarm",
                bit,
                "mdi:alert-outline",
                BinarySensorDeviceClass.PROBLEM,
            )
        )

    async_add_entities(entities)


class CremalinkBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Cremalink binary sensor (diagnostic)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key, name, icon, dev_class):
        """Initialize the binary sensor.

        Args:
            coordinator: The data update coordinator.
            entry: The config entry.
            key: The key to identify the sensor data.
            name: The name of the sensor.
            icon: The icon for the sensor.
            dev_class: The device class of the sensor.
        """
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_device_class = dev_class
        self._connection_type = entry.data.get(CONF_CONNECTION_TYPE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="cremalink",
        )

        self._standby_cache = None

    @property
    def available(self):
        """Unavailable only after the consecutive-failure threshold (T045)."""
        if not self.coordinator.data:
            return False
        if self.coordinator.consecutive_failures >= self.coordinator.failure_threshold:
            return False
        return super().available

    @property
    def is_on(self):
        """Return True if the binary sensor is on.

        While the machine is in a standby-like status it stops evaluating
        alarm/switch bits — a latched bit (e.g. alarm bit 0 on standby
        frames) must not surface as a problem. The last live reading is
        retained instead (T044/FR-034).
        """
        status = getattr(self.coordinator.data, "status_name", None)
        if status in STANDBY_STATUSES:
            return self._standby_cache
        value = self._read()
        if value is not None:
            self._standby_cache = value
        return value

    def _read(self):
        return getattr(self.coordinator.data, self._key, None)


class CremalinkBitSensor(CremalinkBinarySensor):
    """One documented switch/alarm bit of the monitor frame (diagnostic)."""

    def __init__(self, coordinator, entry, source, bit, icon, dev_class):
        """Initialize the bit sensor.

        Args:
            coordinator: The data update coordinator.
            entry: The config entry.
            source: ``"switch"`` or ``"alarm"``.
            bit: The :class:`~cremalink.ecam.monitor_bits.BitDef`.
            icon: The icon for the sensor.
            dev_class: The device class of the sensor.
        """
        shared = {b.key for b in SWITCH_BITS.values()} & {
            b.key for b in ALARM_BITS.values()
        }
        label = f"{bit.label} ({source})" if bit.key in shared else bit.label
        super().__init__(
            coordinator, entry, f"{source}_{bit.key}", label, icon, dev_class
        )
        self._source = source
        self._bit_key = bit.key
        self._attr_entity_registry_enabled_default = bit.common

    def _read(self):
        view = self.coordinator.data
        states = getattr(view, f"{self._source}_states", None)
        return states().get(self._bit_key) if callable(states) else None
