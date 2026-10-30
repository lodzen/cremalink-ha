"""Select platform for the Cremalink integration.

Three selects per contracts/ha-entities.md:

- Profile picker — occupied ``0xA4`` slots; selection sends a session-gated
  ``0xA9``; state is the last acked slot only.
- Auto-off + water hardness — session-gated ``0x90`` writes with ``0x95``
  read-back; state is always a machine-confirmed option.
"""

import logging
from functools import partial

from cremalink.ecam.settings import SETTING_OPTION_MAPS
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity, RestoreStateData
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTION_TYPE, DOMAIN, NOT_READY_STATUSES, STANDBY_STATUSES

_LOGGER = logging.getLogger(__name__)

#: Setting select definitions: (setting key, suffix). The suffix is also the
#: entity translation key (name and option labels).
SETTING_SELECTS = [
    ("auto_off", "setting_auto_off"),
    ("water_hardness", "setting_water_hardness"),
]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the select platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device = data["device"]

    entities = [CremalinkProfileSelect(coordinator, device, entry)]

    capabilities = getattr(device, "capabilities", {}) or {}
    for key, suffix in SETTING_SELECTS:
        setting = SETTING_OPTION_MAPS[key]
        if capabilities and not capabilities.get(setting.capability, True):
            continue
        entities.append(CremalinkSettingSelect(coordinator, device, entry, key, suffix))

    async_add_entities(entities)

    # Prime the machine-confirmed state in the background — the LAN
    # reads cost seconds each on the one-command-per-poll lane
    # (§14.12); awaiting them here would stall platform setup. Entities
    # read as unknown until the refresh lands.
    for entity in entities:
        hass.async_create_task(entity.async_refresh_state())


class _BaseSelect(CoordinatorEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

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

    Non-striker machines have no current-profile read-back — the app
    itself stores the selection app-side and only ever *tells* the
    machine (``0x03EE`` is the striker register; it does not track
    ``0xA9`` selects on Soul). ``Device.refresh_current_profile``
    therefore returns the last-asserted profile; the remembered
    selection is also restored after a restart. Like the official app,
    profile selection is the one setting that is unavailable in standby.
    """

    def __init__(self, coordinator, device, entry):
        super().__init__(coordinator, device, entry)
        self._attr_translation_key = "profile"
        self._attr_unique_id = f"{entry.entry_id}_profile"
        self._attr_icon = "mdi:account"
        self._slots: dict[str, int] = {}  # option label -> profile index
        self._current_option = None
        self._restored_index = None

    @property
    def available(self):
        """Unavailable in standby-like states — the only gated setting."""
        data = self.coordinator.data
        status = getattr(data, "status_name", None) if data else None
        if status is not None and status in NOT_READY_STATUSES:
            return False
        return super().available

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

    def _handle_coordinator_update(self):
        """Adopt the device's current profile between refreshes."""
        self._update_current_option()
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self):
        """The remembered profile, kept independent of the readable slots."""
        index = getattr(self.device, "current_profile", 0)
        return {"profile_index": index} if index else None

    async def async_refresh_state(self):
        try:
            # coordinator.hass — always bound; entity.hass is unset when
            # the setup priming task runs before the entity is added.
            slots = await self.coordinator.hass.async_add_executor_job(
                self.device.get_profiles
            )
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
        # Non-striker applies 0xA9 without an ack (fire-and-forget like
        # the app) — ok means "sent, no nack"; an explicit nack keeps
        # the previous option rather than pretending the selection took.
        if ok:
            self._current_option = option
            self.async_write_ha_state()
            # Home Assistant only saves restorable state on a clean stop and
            # every 15 minutes; a restart soon after selecting would lose it.
            await RestoreStateData.async_save_persistent_states(self.hass)


class CremalinkSettingSelect(_BaseSelect):
    """Writable machine setting backed by a session-gated 0x90 write."""

    def __init__(self, coordinator, device, entry, key, suffix):
        super().__init__(coordinator, device, entry)
        self._key = key
        self._setting = SETTING_OPTION_MAPS[key]
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_icon = "mdi:cog"
        self._current_option = None

    def _label_for(self, index):
        if index is None:
            return None
        return self._setting.options.get(index)

    def _handle_coordinator_update(self):
        """Track machine-side option values between own writes.

        The coordinator refreshes the republished settings datapoints at
        SETTINGS_INTERVAL, so panel-side edits land here within seconds
        (protocol.md §14.11).
        """
        values = getattr(self.coordinator, "settings", None)
        if values is not None:
            option = self._label_for(values.get(self._key))
            if option is not None:
                self._current_option = option
        super()._handle_coordinator_update()

    async def async_refresh_state(self):
        try:
            # coordinator.hass — always bound; entity.hass is unset when
            # the setup priming task runs before the entity is added.
            # Scoped to this select's key+datapoint: a full sweep queues
            # ~6 GETs on the one-command-per-poll lane (§14.12).
            values = await self.coordinator.hass.async_add_executor_job(
                partial(
                    self.device.get_settings,
                    hints={self._setting.datapoint_hint},
                    keys={self._key},
                )
            )
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
        try:
            ok = await self.hass.async_add_executor_job(
                self.device.set_setting, self._key, index
            )
        except (OSError, TimeoutError, RuntimeError) as err:
            raise HomeAssistantError(
                f"The machine did not confirm the change of {self.name}: {err}"
            ) from err
        if not ok:
            raise HomeAssistantError(f"The machine rejected the change of {self.name}.")
        self._current_option = option
        # Patch the coordinator's tracked snapshot with the confirmed
        # value — otherwise its next update restores the pre-write
        # option until the next SETTINGS_INTERVAL fetch (the select
        # visibly flapped back; switch.py does the same for bits).
        values = getattr(self.coordinator, "settings", None)
        if values is not None:
            values[self._key] = index
        self.async_write_ha_state()
