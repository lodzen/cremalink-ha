"""Select platform for the Cremalink integration.

Three selects per contracts/ha-entities.md:

- Profile picker — occupied ``0xA4`` slots; selection sends a session-gated
  ``0xA9``; state is the last acked slot only.
- Auto-off + water hardness — session-gated ``0x90`` writes with ``0x95``
  read-back; state is always a machine-confirmed option.
"""

import logging
import re
import time
from functools import partial

from cremalink.domain.device import BeanSystem
from cremalink.ecam.settings import SETTING_OPTION_MAPS
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import (
    RestoredExtraData,
    RestoreEntity,
    RestoreStateData,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CONNECTION_TYPE,
    DOMAIN,
    NOT_READY_STATUSES,
    STANDBY_STATUSES,
    catalog_ready_signal,
)
from .coordinator import CremalinkCoordinator

_LOGGER = logging.getLogger(__name__)

#: Setting select definitions: (setting key, suffix). The suffix is also the
#: entity translation key (name and option labels).
SETTING_SELECTS = [
    ("auto_off", "setting_auto_off"),
    ("water_hardness", "setting_water_hardness"),
]


#: Custom-recipe slot ids (``0xE6``–``0xEB``) share one catalogue name.
_CUSTOM_SLOT_BASE = 229


def _beverage_label(bev):
    """Fallback label for a recipe without a command-map name."""
    if bev.kind == "custom":
        return f"Custom {bev.bev_id - _CUSTOM_SLOT_BASE}"
    return getattr(bev, "name", None) or f"Beverage {bev.bev_id}"


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

    session = data.get("recipe_session")
    if session is not None:
        entities.append(CremalinkRecipeSelect(coordinator, device, entry, session))

    # BeanAdapt machines advertise d25X_beansystem_1..6 in
    # catalog_datapoints — a static map check, no machine read. Slot
    # names/options land via the background priming below.
    if any(
        re.fullmatch(r"d25\d_beansystem_[1-6]", name)
        for name in getattr(device, "catalog_datapoints", [])
    ):
        entities.append(CremalinkBeanSelect(coordinator, device, entry))

    async_add_entities(entities)

    # Prime the machine-confirmed state in the background — the LAN
    # reads cost seconds each on the one-command-per-poll lane
    # (§14.12); awaiting them here would stall platform setup. Entities
    # read as unknown until the refresh lands.
    for entity in entities:
        hass.async_create_task(entity.async_refresh_state())


class _BaseSelect(CoordinatorEntity[CremalinkCoordinator], SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(self, coordinator, device, entry):
        super().__init__(coordinator)
        self.device = device
        self._asleep = False
        self._options_refresh_retry_at = 0.0
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
            # Retry a failed priming too — booted while the machine was
            # already awake, the asleep->awake transition never happens,
            # and a priming that raced the LAN registration would leave
            # the select empty until a reload (live-observed).
            retry_due = (
                self._needs_options_refresh()
                and time.monotonic() - self._options_refresh_retry_at >= 60
            )
            if awake and (self._asleep or retry_due):
                self._options_refresh_retry_at = time.monotonic()
                self.hass.async_create_task(self._async_refresh_after_wake())
            self._asleep = not awake
        super()._handle_coordinator_update()

    async def async_refresh_state(self):
        """Refresh the option state; implemented by each concrete select."""
        raise NotImplementedError

    def _needs_options_refresh(self) -> bool:
        """True while the machine-side options were never populated —
        signals a failed priming that deserves a throttled retry."""
        return False

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
        extra = await self.async_get_last_extra_data()
        stored = extra.as_dict() if extra else {}
        slots = stored.get("slots") or {}
        if slots:
            self._slots = {str(name): int(idx) for name, idx in slots.items()}
        index = stored.get("profile_index")
        if not isinstance(index, int):
            last = await self.async_get_last_state()
            index = (last.attributes or {}).get("profile_index") if last else None
        if isinstance(index, int) and index > 0:
            self._restored_index = index
            self._apply_restored()
            self._update_current_option()

    @property
    def extra_restore_state_data(self):
        """Persist slot names + remembered index — the standby case
        cannot re-read ``get_profiles``, and the plain-state path loses
        everything once an ``unknown`` state is saved."""
        if not self._slots and not self._restored_index:
            return None
        return RestoredExtraData(
            {
                "slots": self._slots,
                "profile_index": getattr(self.device, "current_profile", 0)
                or self._restored_index,
            }
        )

    def _needs_options_refresh(self) -> bool:
        return not self._slots

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
        try:
            ok = await self.hass.async_add_executor_job(
                self.device.select_profile, index
            )
        except (OSError, TimeoutError, RuntimeError) as err:
            raise HomeAssistantError(
                f"Could not switch the profile to {option}: {err}"
            ) from err
        if not ok:
            raise HomeAssistantError(
                f"The machine did not confirm the switch to profile {option}."
            )
        # Non-striker applies 0xA9 without an ack (fire-and-forget like
        # the app) — ok means "sent, no nack"; an explicit nack keeps
        # the previous option rather than pretending the selection took.
        if ok:
            self._current_option = option
            self.async_write_ha_state()
            # Home Assistant only saves restorable state on a clean stop and
            # every 15 minutes; a restart soon after selecting would lose it.
            await RestoreStateData.async_save_persistent_states(self.hass)


class CremalinkRecipeSelect(_BaseSelect, RestoreEntity):
    """Brewable-recipe picker — the single brew surface (spec FR-001..003).

    Options are the machine-catalogued beverages (``beverage_catalog`` —
    no duplicates, no one-shots). Selecting a recipe is local-only: it
    clears the recipe session's overrides and re-arms the param load; no
    machine write happens here. The load itself runs in the background
    on coordinator updates via ``session.async_ensure_params``. The
    entity is still gated on readiness like the profile select —
    changing the selection while the machine sleeps would discard the
    loaded overrides for a brew it cannot confirm anyway.
    """

    _attr_entity_category = None  # a control entity, not configuration

    def __init__(self, coordinator, device, entry, session):
        super().__init__(coordinator, device, entry)
        self.session = session
        self._attr_translation_key = "recipe"
        self._attr_unique_id = f"{entry.entry_id}_recipe"
        self._attr_icon = "mdi:coffee-maker-outline"
        self._options: dict[str, int] = {}  # label -> beverage_id
        self._options_refetched_at = 0.0
        self._catalog_signal = catalog_ready_signal(entry.entry_id)

    async def async_added_to_hass(self):
        """Re-order the options once the cloud catalogue snapshot lands."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._catalog_signal, self._on_catalog_ready
            )
        )
        # Re-arm the last selected recipe so its param load re-queues on
        # wake — only the selection is restored, never params/overrides
        # (spec: session state is transient).
        last = await self.async_get_last_extra_data()
        stored = last.as_dict().get("selected_beverage") if last else None
        if isinstance(stored, int) and stored > 0:
            self.session.select(stored)

    def _needs_options_refresh(self) -> bool:
        return not self._options

    @property
    def extra_restore_state_data(self):
        """Persist the selected beverage id — without this HA stores
        ``extra_data: null`` and the restore read always comes back
        ``None`` (live-observed: recipe select showed ``unknown`` after
        a restart despite a prior selection)."""
        selected = self.session.selected_beverage
        if not selected:
            return None
        return RestoredExtraData({"selected_beverage": selected})

    @callback
    def _on_catalog_ready(self):
        self.hass.async_create_task(self._async_refresh_after_wake())

    @property
    def available(self):
        """Unavailable while the machine is not ready — same gate as the
        profile select (``NOT_READY_STATUSES``)."""
        data = self.coordinator.data
        status = getattr(data, "status_name", None) if data else None
        if status is not None and status in NOT_READY_STATUSES:
            return False
        return super().available

    def _awake(self) -> bool:
        status = getattr(self.coordinator.data, "status_name", None)
        return status is not None and status not in STANDBY_STATUSES

    def _handle_coordinator_update(self):
        """Drive the session's param load and profile-change re-scope."""
        self.hass.async_create_task(
            self.session.async_ensure_params(self.hass, self.coordinator)
        )
        if self._awake() and not self.device.recipe_priority_loaded():
            # Menu order is one cached GET per profile; retried at most
            # once a minute so a slow machine is never polled per cycle.
            now = time.monotonic()
            if now - self._options_refetched_at >= 60:
                self._options_refetched_at = now
                self.hass.async_create_task(self._async_refresh_after_wake())
        super()._handle_coordinator_update()

    async def async_refresh_state(self):
        """Populate options (executor).

        The recipe list itself is static (model table + command map —
        zero machine requests), so options exist immediately, even in
        standby or before the first monitor lands. Only the drink-menu
        order needs the machine (one GET per profile, cached) and is
        therefore fetched only while the machine is known to be awake
        (protocol.md §13/§14.12, research.md R11).
        """
        try:
            beverages = await self.coordinator.hass.async_add_executor_job(
                partial(self.device.beverage_catalog, fetch_priority=self._awake())
            )
        except (OSError, ValueError, RuntimeError) as err:
            _LOGGER.debug("beverage catalog fetch failed: %s", err)
            return
        if not beverages:
            return
        options: dict[str, int] = {}
        for bev in beverages:
            entry = self.device.brew_entry(bev.bev_id) or {}
            label = entry.get("name") or _beverage_label(bev)
            options.setdefault(label, bev.bev_id)
        self._options = options
        # The priming task can outrun entity attachment (hass is None
        # until added) — the next coordinator update writes state then.
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def options(self):
        return list(self._options)

    @property
    def current_option(self):
        return next(
            (
                label
                for label, bid in self._options.items()
                if bid == self.session.selected_beverage
            ),
            None,
        )

    @property
    def extra_state_attributes(self):
        attrs = {}
        if self.session.selected_beverage:
            attrs["selected_beverage"] = self.session.selected_beverage
        params = self.session.params
        if params is not None:
            attrs.update(
                {
                    "beverage_id": params.beverage_id,
                    "values_source": params.source,
                    **({"bean_slot": params.bean_slot} if params.bean_slot else {}),
                }
            )
        return attrs or None

    async def async_select_option(self, option: str):
        beverage_id = self._options.get(option)
        if beverage_id is None:
            raise ValueError(f"unknown recipe option {option!r}")
        self.session.select(beverage_id)
        self.async_write_ha_state()
        await self.session.async_ensure_params(self.hass, self.coordinator)
        # Persist immediately — the 15-min persist cycle could lose a
        # selection made shortly before a restart (bean select does
        # the same).
        await RestoreStateData.async_save_persistent_states(self.hass)


class CremalinkSettingSelect(_BaseSelect, RestoreEntity):
    """Writable machine setting backed by a session-gated 0x90 write.

    ``RestoreEntity``: standby blocks the settings re-read, so the last
    machine-confirmed option survives a restart; the next successful
    ``0x95`` read still wins.
    """

    def __init__(self, coordinator, device, entry, key, suffix):
        super().__init__(coordinator, device, entry)
        self._key = key
        self._setting = SETTING_OPTION_MAPS[key]
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_icon = "mdi:cog"
        self._current_option = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._setting.options.values():
            self._current_option = last.state

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


class CremalinkBeanSelect(_BaseSelect, RestoreEntity):
    """BeanAdapt bean-system picker — options carry the user-assigned
    bean names from the ``d25X`` blobs (``Device.bean_systems``).

    Selecting sends the real selection frame ``0xB9``
    (``device.select_bean_system``) — a session-gated write on §13's
    untested list, so the entity is gated on readiness like the profile
    select. ``current_option`` always reflects the machine's flagged
    bean, never a locally remembered choice. The options+selection are
    persisted: standby blocks ``d25X`` re-reads, so a restart would
    otherwise leave the select empty until wake (FR-035 pattern).
    """

    _attr_entity_category = None  # a control entity, not configuration

    def __init__(self, coordinator, device, entry):
        super().__init__(coordinator, device, entry)
        self._attr_translation_key = "bean_system"
        self._attr_unique_id = f"{entry.entry_id}_bean_system"
        self._attr_icon = "mdi:beans"
        self._systems: list = []  # BeanSystem list from device.bean_systems()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_extra_data()
        stored = (last.as_dict().get("bean_systems") or []) if last else []
        systems = [
            BeanSystem(int(s["slot"]), str(s["name"]), bool(s.get("selected")))
            for s in stored
            if isinstance(s, dict) and s.get("slot") and s.get("name")
        ]
        if systems:
            self._systems = systems

    def _needs_options_refresh(self) -> bool:
        return not self._systems

    @property
    def extra_state_attributes(self):
        if not self._systems:
            return None
        return {
            "bean_systems": [
                {"slot": s.slot, "name": s.name, "selected": s.selected}
                for s in self._systems
            ]
        }

    @property
    def extra_restore_state_data(self):
        """Persist options+selection for the standby case — without
        this HA stores ``extra_data: null`` and ``d25X`` blobs cannot
        be re-read while the machine sleeps."""
        attrs = self.extra_state_attributes
        return RestoredExtraData(attrs) if attrs else None

    @property
    def available(self):
        """Unavailable while the machine is not ready — a ``0xB9``
        selection is a write, gated like the profile select."""
        data = self.coordinator.data
        status = getattr(data, "status_name", None) if data else None
        if status is not None and status in NOT_READY_STATUSES:
            return False
        return super().available

    async def async_refresh_state(self):
        try:
            systems = await self.coordinator.hass.async_add_executor_job(
                self.device.bean_systems
            )
        except (OSError, ValueError, RuntimeError) as err:
            _LOGGER.debug("bean-system fetch failed: %s", err)
            return
        if systems:
            self._systems = systems

    @property
    def options(self):
        return [s.name for s in self._systems]

    @property
    def current_option(self):
        selected = next((s for s in self._systems if s.selected), None)
        return selected.name if selected else None

    async def async_select_option(self, option: str):
        selected = next((s for s in self._systems if s.name == option), None)
        if selected is None:
            raise ValueError(f"unknown bean-system option {option!r}")
        ok = await self.hass.async_add_executor_job(
            self.device.select_bean_system, selected.slot
        )
        if not ok:
            raise HomeAssistantError(
                f"The machine rejected the bean-system change to {option}."
            )
        # Machine confirmed (or nack-free like 0xA9) — re-read the blobs
        # so current_option follows the machine's flag, not our choice.
        await self.async_refresh_state()
        self.async_write_ha_state()
        # Persist immediately — the 15-min persist cycle could lose a
        # selection made shortly before a restart (profile select does
        # the same).
        await RestoreStateData.async_save_persistent_states(self.hass)
