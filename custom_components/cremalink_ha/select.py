"""Select platform for the Cremalink integration.

Three selects per contracts/ha-entities.md:

- Profile picker — occupied ``0xA4`` slots; selection sends a session-gated
  ``0xA9``; state is the last acked slot only.
- Auto-off + water hardness — session-gated ``0x90`` writes with ``0x95``
  read-back; state is always a machine-confirmed option.
"""

import logging

from cremalink.ecam.settings import SETTING_OPTION_MAPS
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity, RestoreStateData
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTION_TYPE, DOMAIN, STANDBY_STATUSES

_LOGGER = logging.getLogger(__name__)

#: Setting select definitions: (setting key, suffix, display-name prefix).
SETTING_SELECTS = [
    ("auto_off", "setting_auto_off", "Auto-Off"),
    ("water_hardness", "setting_water_hardness", "Water Hardness"),
]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the select platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device = data["device"]

    entities = [CremalinkProfileSelect(coordinator, device, entry)]

    capabilities = getattr(device, "capabilities", {}) or {}
    for key, suffix, name in SETTING_SELECTS:
        setting = SETTING_OPTION_MAPS[key]
        if capabilities and not capabilities.get(setting.capability, True):
            continue
        entities.append(
            CremalinkSettingSelect(coordinator, device, entry, key, suffix, name)
        )

    async_add_entities(entities)

    # Prime the machine-confirmed state (LAN reads run in the executor).
    for entity in entities:
        await entity.async_refresh_state()


class _BaseSelect(CoordinatorEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device, entry):
        super().__init__(coordinator)
        self.device = device
        self._asleep = False
        self._connection_type = entry.data.get(CONF_CONNECTION_TYPE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="cremalink",
        )

    @property
    def available(self):
        if not self.coordinator.data:
            return False
        if self.coordinator.consecutive_failures >= self.coordinator.failure_threshold:
            return False
        return super().available

    def _handle_coordinator_update(self):
        """Re-read machine-side state once the machine has woken up.

        Profile names and settings are only primed at setup; a machine that
        was asleep then (or edited on its display meanwhile) would keep
        showing stale values until a reload.
        """
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


class CremalinkProfileSelect(_BaseSelect, RestoreEntity):
    """Occupied profile slots; selection is a session-gated 0xA9 write.

    The machine does not report its active profile, so the last selection
    made here is stored with the entity state and restored after a restart.
    """

    def __init__(self, coordinator, device, entry):
        super().__init__(coordinator, device, entry)
        self._attr_name = "Profile"
        self._attr_unique_id = f"{entry.entry_id}_profile"
        self._attr_icon = "mdi:account"
        self._slots: dict[str, int] = {}  # option label -> profile index
        self._current_option = None
        self._restored_index = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        index = (last.attributes or {}).get("profile_index") if last else None
        if isinstance(index, int) and index > 0:
            self._restored_index = index
            self._apply_restored()
            self._update_current_option()

    def _apply_restored(self):
        """Hand the remembered selection to the device once slots are known."""
        if not self._restored_index or getattr(self.device, "current_profile", 0):
            return
        if self._restored_index in self._slots.values():
            self.device.current_profile = self._restored_index

    def _update_current_option(self):
        """Map the device's current profile to an option label.

        Recomputed on every read so a renamed slot never leaves a label
        that is no longer one of the options.
        """
        if not self._slots:
            return
        current = getattr(self.device, "current_profile", 0)
        self._current_option = next(
            (label for label, index in self._slots.items() if index == current),
            None,
        )

    @property
    def extra_state_attributes(self):
        """The remembered profile, kept independent of the readable slots."""
        index = getattr(self.device, "current_profile", 0)
        return {"profile_index": index} if index else None

    async def async_refresh_state(self):
        try:
            slots = await self.hass.async_add_executor_job(self.device.get_profiles)
        except (OSError, ValueError, RuntimeError) as err:
            _LOGGER.debug("Profile fetch failed: %s", err)
            return
        if not slots:
            # A machine that answers nothing must not wipe what we know.
            return
        self._slots = {slot.name: slot.index for slot in slots}
        self._apply_restored()
        self._update_current_option()

    @property
    def options(self):
        return list(self._slots)

    @property
    def current_option(self):
        return self._current_option

    async def async_select_option(self, option: str):
        index = self._slots.get(option)
        if index is None:
            raise ValueError(f"unknown profile option {option!r}")
        ok = await self.hass.async_add_executor_job(self.device.select_profile, index)
        # Report only machine-confirmed state — a failed ack keeps the
        # previous option rather than pretending the selection took.
        if ok:
            self._current_option = option
            self.async_write_ha_state()
            # Home Assistant only saves restorable state on a clean stop and
            # every 15 minutes; a restart soon after selecting would lose it.
            await RestoreStateData.async_save_persistent_states(self.hass)


class CremalinkSettingSelect(_BaseSelect):
    """Writable machine setting backed by a session-gated 0x90 write."""

    def __init__(self, coordinator, device, entry, key, suffix, name):
        super().__init__(coordinator, device, entry)
        self._key = key
        self._setting = SETTING_OPTION_MAPS[key]
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_icon = "mdi:cog"
        self._current_option = None

    def _label_for(self, index):
        if index is None:
            return None
        return self._setting.options.get(index)

    async def async_refresh_state(self):
        try:
            values = await self.hass.async_add_executor_job(self.device.get_settings)
        except (OSError, ValueError, RuntimeError) as err:
            _LOGGER.debug("Settings fetch failed: %s", err)
            return
        self._current_option = self._label_for(values.get(self._key))

    @property
    def options(self):
        return [self._setting.options[i] for i in sorted(self._setting.options)]

    @property
    def current_option(self):
        return self._current_option

    async def async_select_option(self, option: str):
        index = next(
            (i for i, label in self._setting.options.items() if label == option),
            None,
        )
        if index is None:
            raise ValueError(f"unknown option {option!r} for {self._key}")
        ok = await self.hass.async_add_executor_job(
            self.device.set_setting, self._key, index
        )
        if ok:
            self._current_option = option
            self.async_write_ha_state()
