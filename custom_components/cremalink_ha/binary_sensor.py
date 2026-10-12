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

#: Monitor predicates: (key, icon, device class). Names come from the entity
#: translations, keyed by ``key``.
BINARY_SENSORS = [
    ("is_busy", None, BinarySensorDeviceClass.RUNNING),
    ("is_idle", "mdi:sleep", None),
    ("is_watertank_open", "mdi:water-boiler-alert", BinarySensorDeviceClass.DOOR),
    ("is_watertank_empty", "mdi:water-off", BinarySensorDeviceClass.PROBLEM),
    ("is_waste_container_full", "mdi:delete-alert", BinarySensorDeviceClass.PROBLEM),
    (
        "is_waste_container_missing",
        "mdi:delete-alert",
        BinarySensorDeviceClass.PROBLEM,
    ),
]

#: BINARY_SENSORS keys that stay in the normal entity section; anything
#: else (Idle, every switch/alarm bit sensor) is diagnostic.
_PRIMARY_BINARY_KEYS = {
    "is_busy",
    "is_watertank_open",
    "is_watertank_empty",
    "is_waste_container_full",
    "is_waste_container_missing",
}


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
    for key, icon, dev_class in BINARY_SENSORS:
        entities.append(CremalinkBinarySensor(coordinator, entry, key, icon, dev_class))

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
    """Representation of a Cremalink binary sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, icon, dev_class):
        """Initialize the binary sensor.

        Args:
            coordinator: The data update coordinator.
            entry: The config entry.
            key: The key to identify the sensor data (also its translation key).
            icon: The icon for the sensor.
            dev_class: The device class of the sensor.
        """
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_device_class = dev_class
        self._attr_entity_category = (
            None if key in _PRIMARY_BINARY_KEYS else EntityCategory.DIAGNOSTIC
        )
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
            if self._key == "is_busy":
                # The action byte stays latched from the last drink in
                # standby — the machine is not actually busy.
                return False
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
        super().__init__(coordinator, entry, f"{source}_{bit.key}", icon, dev_class)
        self._source = source
        self._bit_key = bit.key
        self._attr_entity_registry_enabled_default = bit.common

    def _read(self):
        view = self.coordinator.data
        states = getattr(view, f"{self._source}_states", None)
        return states().get(self._bit_key) if callable(states) else None
