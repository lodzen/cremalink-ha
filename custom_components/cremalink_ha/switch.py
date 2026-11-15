"""Switch platform for the Cremalink integration.

- Power — the device's on/standby control (no entity category).
- Param-63 bit settings (beep, energy saving, …) — configuration
  switches backed by a session-gated ``0x90`` write that merges the flag
  into the shared user-config word (``Device.set_setting_bit``).
"""

import logging
import time
from functools import partial

from cremalink.ecam.settings import SETTING_BIT_MAPS
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BUTTON_UNAVAILABLE_STATUSES,
    CONF_CONNECTION_TYPE,
    DOMAIN,
    NOT_BREWING_STATUSES,
    NOT_READY_STATUSES,
    STANDBY_STATUSES,
)
from .coordinator import CremalinkCoordinator

#: How long the switch shows the commanded state before trusting the
#: monitor again (a wake-up was seen to report only after ~3 min).
POWER_PENDING_SECONDS = 240

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
    session = data.get("recipe_session")
    if session is not None:
        entities.append(CremalinkBrewSwitch(coordinator, device, session, entry))
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
        # (target state, monotonic deadline) after a command: the machine
        # takes 30 s to minutes to report waking up or going to sleep, and
        # the switch must not snap back meanwhile.
        self._pending: tuple[bool, float] | None = None

    def _reported_on(self) -> bool | None:
        if not self.coordinator.data or not self.coordinator.data.status_name:
            return None
        return self.coordinator.data.status_name.lower() not in {"standby"} | (
            STANDBY_STATUSES - {"going_to_sleep"}
        )

    @property
    def is_on(self):
        """Return true if the switch is on."""
        reported = self._reported_on()
        if self._pending is not None:
            target, deadline = self._pending
            if reported == target or time.monotonic() >= deadline:
                self._pending = None
            else:
                return target
        return reported

    @property
    def available(self):
        """Return True if entity is available."""
        if not self.coordinator.data:
            return False
        return super().available

    async def _async_power(self, command: str, target: bool) -> None:
        try:
            await self.hass.async_add_executor_job(self.device.do, command)
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
            raise HomeAssistantError(
                f"Could not send '{command}' to the machine: {err}"
            ) from err
        self._pending = (target, time.monotonic() + POWER_PENDING_SECONDS)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self._async_power("wakeup", True)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self._async_power("standby", False)


class CremalinkSettingSwitch(
    CoordinatorEntity[CremalinkCoordinator], SwitchEntity, RestoreEntity
):
    """A boolean flag inside the shared param-63 user-config word.

    Writes go through ``Device.set_setting_bit``: the current word is read
    first and the flag merged in, so unrelated bits survive (protocol.md
    §14.8). While a write waits for the machine's confirmation (over the
    cloud up to ~45 s) the switch shows the requested value; a write the
    machine does not confirm restores the previous one.
    ``RestoreEntity`` keeps the last confirmed state visible across a
    restart when standby blocks the re-read; a successful fetch wins.
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
        #: Requested value while a write awaits confirmation.
        self._pending: bool | None = None
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_icon = icon
        self._connection_type = entry.data.get(CONF_CONNECTION_TYPE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="cremalink",
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._is_on = last.state == "on"

    @property
    def is_on(self):
        """Requested state during a write, else the machine-confirmed one."""
        if self._pending is not None:
            return self._pending
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
        """Write the flag, showing the requested value until confirmed."""
        self._pending = on
        self.async_write_ha_state()
        try:
            ok = await self.hass.async_add_executor_job(
                self.device.set_setting_bit, self._key, on
            )
        except (OSError, TimeoutError, RuntimeError) as err:
            self._pending = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"The machine did not confirm the change of {self.name}: {err}"
            ) from err
        self._pending = None
        if not ok:
            self.async_write_ha_state()
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


class CremalinkBrewSwitch(CoordinatorEntity[CremalinkCoordinator], SwitchEntity):
    """One entity for brew + stop — the recipe stays in ``select.recipe``.

    ON while the monitor reports a brewing action — also when the brew
    was started at the machine's own panel. ``turn_on`` sends the
    session's effective values (stored + pending overrides) in one
    ``0x83`` frame via ``device.brew`` — transient, never persisted;
    ``turn_off`` sends ``stop`` (a ``beverage_id`` command,
    action=STOPV2), harmless when idle. Replaces the former
    ``button.brew_recipe`` + ``button.cmd_stop`` pair.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, device, session, entry):
        super().__init__(coordinator)
        self.device = device
        self.session = session
        self._attr_translation_key = "brew_recipe"
        self._attr_unique_id = f"{entry.entry_id}_brew_recipe"
        self._attr_icon = "mdi:coffee"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="cremalink",
        )

    def _brewing(self):
        """Monitor says a brewing action is running (same rule the drink
        buttons used): non-standby status + the busy/action byte set."""
        data = self.coordinator.data
        return bool(
            data
            and data.status_name is not None
            and data.status_name not in NOT_BREWING_STATUSES
            and data.is_busy
        )

    @property
    def is_on(self):
        data = self.coordinator.data
        if not data or data.status_name is None:
            return None
        return self._brewing()

    @property
    def available(self):
        """Stoppable while brewing; brewable when the machine is ready
        and the session holds a loaded recipe (spec clarification Q3)."""
        data = self.coordinator.data
        if not super().available or not data or data.status_name is None:
            return False
        if self._brewing():
            return True
        if data.status_name in BUTTON_UNAVAILABLE_STATUSES:
            return False
        return self.session.ready

    async def async_turn_on(self, **kwargs):
        data = self.coordinator.data
        if data:
            if data.status_name in NOT_READY_STATUSES:
                raise HomeAssistantError("The machine is not ready; turn it on first.")
            if data.is_busy:
                raise HomeAssistantError("The machine is busy; wait until it is ready.")
        beverage_id = self.session.selected_beverage
        if beverage_id is None:
            raise HomeAssistantError("Select a recipe first.")
        # `available` is UI-only — a service call must not brew with
        # params that are missing, loading, or scoped to a stale
        # recipe/profile (US5).
        if not self.session.ready:
            raise HomeAssistantError(
                "Recipe parameters are not loaded yet for the selected "
                "recipe/profile — wait for them to appear, then brew."
            )
        await self.hass.async_add_executor_job(
            partial(
                self.device.brew,
                beverage_id,
                overrides=dict(self.session.overrides),
                params=self.session.params,
            )
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self.hass.async_add_executor_job(self.device.do, "stop")
        await self.coordinator.async_request_refresh()
