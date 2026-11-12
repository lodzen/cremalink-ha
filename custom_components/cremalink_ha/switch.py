"""Switch platform for the Cremalink integration.

- Power — the device's on/standby control (no entity category).
- Param-63 bit settings (beep, energy saving, …) — configuration
  switches backed by a session-gated ``0x90`` write that merges the flag
  into the shared user-config word (``Device.set_setting_bit``).
"""

import logging

from cremalink.ecam.settings import SETTING_BIT_MAPS
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTION_TYPE, DOMAIN, STANDBY_STATUSES
from .coordinator import CremalinkCoordinator

_LOGGER = logging.getLogger(__name__)

#: Bit-setting switch definitions: (setting key, translation-key suffix,
#: icon). The suffix doubles as the unique-id tail.
SETTING_SWITCHES = [
    ("beep", "setting_beep", "mdi:vibrate"),
    ("energy_saving", "setting_energy_saving", "mdi:leaf"),
]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the switch platform.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry.
        async_add_entities: Function to add entities.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device = data["device"]
    entities = [CremalinkPowerSwitch(coordinator, device, entry)]
    capabilities = getattr(device, "capabilities", {}) or {}
    for key, suffix, icon in SETTING_SWITCHES:
        setting = SETTING_BIT_MAPS[key]
        if capabilities and not capabilities.get(setting.capability, True):
            continue
        entities.append(
            CremalinkSettingSwitch(coordinator, device, entry, key, suffix, icon)
        )
    async_add_entities(entities)

    # Prime the machine-confirmed bit states in the background — the LAN
    # reads cost seconds each on the one-command-per-poll lane (§14.12);
    # awaiting them here would stall platform setup.
    for entity in entities:
        if isinstance(entity, CremalinkSettingSwitch):
            hass.async_create_task(entity.async_refresh_state())


class CremalinkPowerSwitch(CoordinatorEntity[CremalinkCoordinator], SwitchEntity):
    """Representation of a Cremalink power switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "power"

    def __init__(self, coordinator, device, entry):
        """Initialize the switch.

        Args:
            coordinator: The data update coordinator.
            device: The Cremalink device instance.
            entry: The config entry.
        """
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_icon = "mdi:power"
        self._connection_type = entry.data.get(CONF_CONNECTION_TYPE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="cremalink",
        )

    @property
    def is_on(self):
        """Return true if the switch is on."""
        if not self.coordinator.data or not self.coordinator.data.status_name:
            return None
        # Check if the status indicates the device is not in standby
        return self.coordinator.data.status_name.lower() not in [
            "standby",
            "in_standby",
        ]

    @property
    def available(self):
        """Return True if entity is available."""
        if not self.coordinator.data:
            return False
        return super().available

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self.hass.async_add_executor_job(self.device.do, "wakeup")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self.hass.async_add_executor_job(self.device.do, "standby")
        await self.coordinator.async_request_refresh()


class CremalinkSettingSwitch(CoordinatorEntity[CremalinkCoordinator], SwitchEntity):
    """A boolean flag inside the shared param-63 user-config word.

    Writes go through ``Device.set_setting_bit``: the current word is read
    first and the flag merged in, so unrelated bits survive (protocol.md
    §14.8). State only ever reflects machine-confirmed values.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(self, coordinator, device, entry, key, suffix, icon):
        """Initialize the setting switch.

        Args:
            coordinator: The data update coordinator.
            device: The Cremalink device instance.
            entry: The config entry.
            key: The ``SETTING_BIT_MAPS`` key (e.g. ``beep``).
            suffix: Unique-id tail and entity translation key.
            icon: MDI icon.
        """
        super().__init__(coordinator)
        self.device = device
        self._key = key
        self._setting = SETTING_BIT_MAPS[key]
        self._asleep = False
        self._is_on = None
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_icon = icon
        self._connection_type = entry.data.get(CONF_CONNECTION_TYPE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="cremalink",
        )

    @property
    def is_on(self):
        """Last machine-confirmed bit state (None = unread yet)."""
        return self._is_on

    @property
    def available(self):
        """Return True if entity is available."""
        if not self.coordinator.data:
            return False
        if self.coordinator.consecutive_failures >= self.coordinator.failure_threshold:
            return False
        return super().available

    def _handle_coordinator_update(self):
        """Track machine-side state between own writes.

        The coordinator refreshes the republished settings datapoints at
        SETTINGS_INTERVAL — panel-side edits land in ``setting_bits``
        within seconds (protocol.md §14.11). A wake transition still
        triggers an immediate re-read so post-sleep state is primed
        without waiting for the interval.
        """
        bits = getattr(self.coordinator, "setting_bits", None)
        if bits is not None and bits.get(self._key) is not None:
            self._is_on = bits[self._key]
        status = getattr(self.coordinator.data, "status_name", None)
        if status is not None:
            awake = status not in STANDBY_STATUSES and status != "waking_up"
            if awake and self._asleep:
                self.hass.async_create_task(self._async_refresh_after_wake())
            self._asleep = not awake
        super()._handle_coordinator_update()

    async def _async_refresh_after_wake(self):
        await self.async_refresh_state()
        self.async_write_ha_state()

    async def async_refresh_state(self):
        """Re-read the param-63 word and update this flag's state."""
        try:
            # coordinator.hass — always bound; entity.hass is unset when
            # the setup priming task runs before the entity is added.
            bits = await self.coordinator.hass.async_add_executor_job(
                self.device.get_setting_bits
            )
        except (OSError, ValueError, RuntimeError) as err:
            _LOGGER.debug("Setting-bits fetch failed: %s", err)
            return
        self._is_on = bits.get(self._key)

    async def _async_set(self, on):
        """Write the flag; only a machine-confirmed write updates state."""
        try:
            ok = await self.hass.async_add_executor_job(
                self.device.set_setting_bit, self._key, on
            )
        except (OSError, TimeoutError, RuntimeError) as err:
            raise HomeAssistantError(
                f"The machine did not confirm the change of {self.name}: {err}"
            ) from err
        if not ok:
            raise HomeAssistantError(f"The machine rejected the change of {self.name}.")
        self._is_on = on
        # The write is machine-confirmed — patch the coordinator's
        # tracked snapshot too, or its next update would restore the
        # pre-write value until the next SETTINGS_INTERVAL fetch lands
        # (observed 2026-10-30: the switch visibly flapped back).
        bits = getattr(self.coordinator, "setting_bits", None)
        if bits is not None:
            bits[self._key] = on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """Turn the setting on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs):
        """Turn the setting off."""
        await self._async_set(False)
