"""Entity organisation: categories, Stop availability, bit sensors, wake refresh."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cremalink.ecam.monitor_bits import ALARM_BITS, SWITCH_BITS
from cremalink.ecam.profiles import ProfileSlot
from cremalink.ecam.settings import SETTING_OPTION_MAPS
from custom_components.cremalink_ha import binary_sensor as bs_mod
from custom_components.cremalink_ha import button as button_mod
from custom_components.cremalink_ha import select as select_mod
from custom_components.cremalink_ha import sensor as sensor_mod
from custom_components.cremalink_ha import switch as switch_mod
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)

TRANSLATIONS = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "cremalink_ha"
    / "translations"
)


async def _setup(hass, module, monitor, **dev):
    device = make_device(**dev)
    device.get_commands = lambda: ["espresso", "stop", "wakeup"]
    return await setup_entities(hass, make_entry(), device, module, monitor)


def _by_uid(entities, uid):
    return next(e for e in entities if e.unique_id == uid)


class _View(FakeMonitorData):
    """Monitor stand-in exposing the bit-state accessors of MonitorView."""

    def __init__(self, switches=None, alarms=None, **fields):
        super().__init__(**fields)
        self._switches, self._alarms = switches or {}, alarms or {}

    def switch_states(self):
        return self._switches

    def alarm_states(self):
        return self._alarms


class TestStopButton:
    async def test_unavailable_in_standby_even_with_latched_action(self, hass):
        monitor = FakeMonitorData(status_name="in_standby", is_busy=True)
        _, entities = await _setup(hass, button_mod, monitor)
        assert _by_uid(entities, "entry1_cmd_stop").available is False

    async def test_available_only_while_a_brew_runs(self, hass):
        busy = FakeMonitorData(status_name="ready", is_busy=True)
        coordinator, entities = await _setup(hass, button_mod, busy)
        stop = _by_uid(entities, "entry1_cmd_stop")
        assert stop.available is True
        coordinator.data = FakeMonitorData(status_name="ready", is_busy=False)
        assert stop.available is False
        # Wake-up and rinse also move the action byte, but are no brew.
        for status in ("waking_up", "rinsing", "going_to_sleep", "in_standby"):
            coordinator.data = FakeMonitorData(status_name=status, is_busy=True)
            assert stop.available is False, status

    async def test_stop_is_always_sent_when_pressed(self, hass):
        calls = []
        _, entities = await _setup(
            hass,
            button_mod,
            FakeMonitorData(status_name="ready", is_busy=False),
            do=calls.append,
        )
        await _by_uid(entities, "entry1_cmd_stop").async_press()
        await hass.async_block_till_done()
        assert calls == ["stop"]


class TestBrewButtons:
    async def test_unavailable_in_standby_and_while_waking_but_not_while_going_to_sleep(
        self, hass
    ):
        coordinator, entities = await _setup(
            hass, button_mod, FakeMonitorData(status_name="ready", is_busy=False)
        )
        espresso = _by_uid(entities, "entry1_cmd_espresso")
        for status, expected in (
            ("ready", True),
            ("going_to_sleep", True),  # the transition itself keeps them available
            ("in_standby", False),
            ("waking_up", False),
            ("rinsing", True),
            ("ready", True),
        ):
            coordinator.data = FakeMonitorData(status_name=status, is_busy=False)
            assert espresso.available is expected, status

    async def test_going_to_sleep_does_not_change_any_button(self, hass):
        # The transition into standby must not grey any button out, even
        # though the action byte is latched (busy) during the sleep sequence.
        coordinator, entities = await _setup(
            hass, button_mod, FakeMonitorData(status_name="ready", is_busy=False)
        )
        before = {e.unique_id: e.available for e in entities}
        for _ in range(3):
            coordinator.data = FakeMonitorData(
                status_name="going_to_sleep", is_busy=True
            )
            assert {e.unique_id: e.available for e in entities} == before

    async def test_unavailable_until_the_first_status_is_known(self, hass):
        # Startup: an empty first reading must not briefly report "available"
        # (that would be a state change Home Assistant logs as a button press).
        _, entities = await _setup(hass, button_mod, FakeMonitorData(status_name=None))
        for entity in entities:
            assert entity.available is False

    async def test_only_stop_is_available_while_a_brew_runs(self, hass):
        coordinator, entities = await _setup(
            hass, button_mod, FakeMonitorData(status_name="ready", is_busy=False)
        )
        espresso = _by_uid(entities, "entry1_cmd_espresso")
        stop = _by_uid(entities, "entry1_cmd_stop")
        assert (espresso.available, stop.available) == (True, False)
        coordinator.data = FakeMonitorData(status_name="ready", is_busy=True)
        assert (espresso.available, stop.available) == (False, True)
        coordinator.data = FakeMonitorData(status_name="ready", is_busy=False)
        assert (espresso.available, stop.available) == (True, False)

    async def test_standby_makes_every_button_unavailable_despite_latched_action(
        self, hass
    ):
        _, entities = await _setup(
            hass, button_mod, FakeMonitorData(status_name="in_standby", is_busy=True)
        )
        for entity in entities:
            assert entity.available is False

    async def test_press_when_ready_brews(self, hass):
        calls = []
        _, entities = await _setup(
            hass,
            button_mod,
            FakeMonitorData(status_name="ready", is_busy=False),
            do=calls.append,
        )
        await _by_uid(entities, "entry1_cmd_espresso").async_press()
        await hass.async_block_till_done()
        assert calls == ["espresso"]

    async def test_press_is_rejected_when_busy_or_not_ready(self, hass):
        calls = []
        for status, busy in (
            ("ready", True),
            ("in_standby", False),
            ("waking_up", False),
        ):
            _, entities = await _setup(
                hass,
                button_mod,
                FakeMonitorData(status_name=status, is_busy=busy),
                do=calls.append,
            )
            with pytest.raises(HomeAssistantError):
                await _by_uid(entities, "entry1_cmd_espresso").async_press()
        assert calls == []


class TestEntityCategories:
    async def test_setting_selects_are_config(self, hass):
        _, entities = await _setup(
            hass, select_mod, FakeMonitorData(status_name="ready")
        )
        assert {e.unique_id for e in entities} >= {
            "entry1_profile",
            "entry1_setting_auto_off",
            "entry1_setting_water_hardness",
        }
        for entity in entities:
            assert entity.entity_category == EntityCategory.CONFIG

    async def test_monitor_sensor_categories(self, hass):
        _, entities = await _setup(
            hass, sensor_mod, FakeMonitorData(status_name="ready")
        )
        for uid in ("status_name", "progress_percent", "accessory_name"):
            assert _by_uid(entities, f"entry1_{uid}").entity_category is None
        assert "entry1_action_code" not in {e.unique_id for e in entities}
        stats = [e for e in entities if "_stat_" in e.unique_id]
        assert stats
        assert all(e.entity_category is None for e in stats)

    async def test_binary_sensor_categories(self, hass):
        _, entities = await _setup(hass, bs_mod, FakeMonitorData(status_name="ready"))
        primary = {
            "is_busy",
            "is_watertank_open",
            "is_watertank_empty",
            "is_waste_container_full",
            "is_waste_container_missing",
        }
        for entity in entities:
            key = entity.unique_id.removeprefix("entry1_")
            assert entity.entity_category is (
                None if key in primary else EntityCategory.DIAGNOSTIC
            )

    async def test_busy_is_off_in_standby_despite_a_latched_action_byte(self, hass):
        # In standby the monitor's action byte stays latched from the last
        # drink; Busy must still read off.
        _, entities = await _setup(
            hass, bs_mod, FakeMonitorData(status_name="in_standby", is_busy=True)
        )
        assert _by_uid(entities, "entry1_is_busy").is_on is False
        _, entities = await _setup(
            hass, bs_mod, FakeMonitorData(status_name="ready", is_busy=True)
        )
        assert _by_uid(entities, "entry1_is_busy").is_on is True


class TestBitSensors:
    async def test_one_entity_per_documented_bit_with_unique_names(self, hass):
        _, entities = await _setup(hass, bs_mod, _View(status_name="ready"))
        bit_uids = {
            e.unique_id
            for e in entities
            if e.unique_id.split("_", 1)[1][:6] in ("switch", "alarm_")
        }
        assert len(bit_uids) == len(SWITCH_BITS) + len(ALARM_BITS)
        names = [e._attr_translation_key or e._attr_name for e in entities]
        assert len(names) == len(set(names))

    async def test_clean_knob_and_motor_position_follow_the_frame(self, hass):
        monitor = _View(
            status_name="ready",
            switches={"clean_knob": True, "motor_up": True, "motor_down": False},
        )
        coordinator, entities = await _setup(hass, bs_mod, monitor)
        assert _by_uid(entities, "entry1_switch_clean_knob").is_on is True
        assert _by_uid(entities, "entry1_switch_motor_up").is_on is True
        assert _by_uid(entities, "entry1_switch_motor_down").is_on is False
        coordinator.data = _View(status_name="ready", alarms={"descale": True})
        assert _by_uid(entities, "entry1_alarm_descale").is_on is True

    async def test_standby_keeps_last_live_reading(self, hass):
        coordinator, entities = await _setup(
            hass, bs_mod, _View(status_name="ready", alarms={"descale": False})
        )
        sensor = _by_uid(entities, "entry1_alarm_descale")
        assert sensor.is_on is False
        # Latched bit in a standby frame must not surface.
        coordinator.data = _View(status_name="in_standby", alarms={"descale": True})
        assert sensor.is_on is False

    async def test_rare_hardware_faults_disabled_by_default(self, hass):
        _, entities = await _setup(hass, bs_mod, _View(status_name="ready"))
        assert (
            _by_uid(
                entities, "entry1_alarm_spi_comm_problem"
            ).entity_registry_enabled_default
            is False
        )
        assert (
            _by_uid(
                entities, "entry1_alarm_beans_empty"
            ).entity_registry_enabled_default
            is True
        )


class TestWakeRefresh:
    def _profiles(self, names):
        return lambda: [
            ProfileSlot(index=i + 1, name=n, icon=0) for i, n in enumerate(names)
        ]

    async def test_profile_names_reread_when_machine_wakes(self, hass):
        names = ["Alice"]
        calls = []
        coordinator, entities = await _setup(
            hass,
            select_mod,
            FakeMonitorData(status_name="in_standby"),
            get_profiles=lambda: calls.append(1) or self._profiles(names)(),
        )
        profile = _by_uid(entities, "entry1_profile")
        await hass.async_block_till_done()
        assert calls == [1]  # priming only
        assert profile.options == ["Alice"]

        profile._handle_coordinator_update()  # still asleep: nothing scheduled
        await hass.async_block_till_done()
        assert calls == [1]

        names.append("Bob")  # renamed/added on the machine meanwhile
        coordinator.data = FakeMonitorData(status_name="ready")
        profile._handle_coordinator_update()
        await hass.async_block_till_done()
        assert calls == [1, 1]
        assert profile.options == ["Alice", "Bob"]

    async def test_waking_up_status_does_not_refresh_yet(self, hass):
        calls = []
        coordinator, entities = await _setup(
            hass,
            select_mod,
            FakeMonitorData(status_name="in_standby"),
            get_profiles=lambda: calls.append(1) or self._profiles(["x"])(),
        )
        profile = _by_uid(entities, "entry1_profile")
        await hass.async_block_till_done()
        calls.clear()
        profile._handle_coordinator_update()
        coordinator.data = FakeMonitorData(status_name="waking_up")
        profile._handle_coordinator_update()
        await hass.async_block_till_done()
        assert calls == []

    async def test_no_refresh_when_already_awake(self, hass):
        calls = []
        _, entities = await _setup(
            hass,
            select_mod,
            FakeMonitorData(status_name="ready"),
            get_profiles=lambda: calls.append(1) or self._profiles(["x"])(),
        )
        profile = _by_uid(entities, "entry1_profile")
        await hass.async_block_till_done()
        calls.clear()
        profile._handle_coordinator_update()
        profile._handle_coordinator_update()
        await hass.async_block_till_done()
        assert calls == []


def _en_entity_names():
    data = json.loads((TRANSLATIONS / "en.json").read_text())
    return data["entity"]


def _label(entity, en_names):
    """The entity's own name part — what the integration declares.

    Registry-level name resolution (device + entity) is HA's machinery;
    here we check the declared translation_key → strings label or the
    raw _attr_name for translation-less entities. The platform domain is
    the entity module's basename (sensor.py → "sensor", ...).
    """
    domain = type(entity).__module__.rsplit(".", 1)[-1]
    key = entity._attr_translation_key
    if key:
        return en_names.get(domain, {}).get(key, {}).get("name")
    return getattr(entity, "_attr_name", None)


class TestCleanNames:
    async def test_no_entity_name_carries_the_device_title(self, hass):
        en_names = _en_entity_names()
        for module in (sensor_mod, bs_mod, select_mod, button_mod, switch_mod):
            _, entities = await _setup(hass, module, _View(status_name="ready"))
            assert entities
            for entity in entities:
                label = _label(entity, en_names)
                assert "Soul" not in (label or ""), (module.__name__, label)

    async def test_expected_clean_names(self, hass):
        en_names = _en_entity_names()
        _, sensors = await _setup(
            hass, sensor_mod, FakeMonitorData(status_name="ready")
        )
        assert _label(_by_uid(sensors, "entry1_status_name"), en_names) == "Status"
        _, selects = await _setup(
            hass, select_mod, FakeMonitorData(status_name="ready")
        )
        assert _label(_by_uid(selects, "entry1_profile"), en_names) == "Profile"
        assert (
            _label(_by_uid(selects, "entry1_setting_auto_off"), en_names) == "Auto-Off"
        )
        assert (
            _label(_by_uid(selects, "entry1_setting_water_hardness"), en_names)
            == "Water Hardness"
        )


class _Last:
    """A stored entity state, as ``RestoreEntity.async_get_last_state`` returns."""

    def __init__(self, state, attributes):
        self.state, self.attributes = state, attributes


class TestProfileRestore:
    async def _profile(self, hass, last, current=0):
        _, entities = await _setup(
            hass,
            select_mod,
            FakeMonitorData(status_name="ready"),
            get_profiles=lambda: [
                ProfileSlot(index=1, name="Alice", icon=0),
                ProfileSlot(index=2, name="Bob", icon=0),
            ],
            current_profile=current,
        )
        profile = _by_uid(entities, "entry1_profile")
        # Re-run the restore path with a stored state — entities were already
        # attached (and `async_added_to_hass` ran) before we could seed it.
        profile.async_get_last_state = AsyncMock(return_value=last)
        await profile.async_added_to_hass()
        return profile

    async def test_last_selection_survives_a_restart(self, hass):
        profile = await self._profile(hass, _Last("Bob", {"profile_index": 2}))
        assert profile.current_option == "Bob"
        assert profile.device.current_profile == 2  # brews use it too
        assert profile.extra_state_attributes == {"profile_index": 2}

    async def test_restore_before_slots_are_read_applies_after_refresh(self, hass):
        profile = await self._profile(hass, _Last("Bob", {"profile_index": 2}))
        profile._slots = {}
        profile._current_option = None
        assert profile.current_option is None  # nothing to map onto yet
        await profile.async_refresh_state()
        assert profile.current_option == "Bob"

    async def test_missing_or_vanished_profile_stays_unknown(self, hass):
        for last in (None, _Last("unknown", {}), _Last("Zed", {"profile_index": 5})):
            profile = await self._profile(hass, last)
            assert profile.current_option is None
            assert profile.device.current_profile == 0

    async def test_selection_forces_a_restore_state_flush(self, hass, monkeypatch):
        from homeassistant.helpers.restore_state import RestoreStateData

        save = AsyncMock()
        monkeypatch.setattr(RestoreStateData, "async_save_persistent_states", save)
        profile = await self._profile(hass, None)
        # The real library records the profile when the 0xA9 ack arrives.
        profile.device.select_profile = lambda index: (
            setattr(profile.device, "current_profile", index) or True
        )
        await profile.async_select_option("Bob")
        save.assert_awaited_once()
        assert profile.extra_state_attributes == {"profile_index": 2}

    async def test_attribute_survives_an_empty_slot_read(self, hass):
        profile = await self._profile(hass, None, current=2)
        assert profile.current_option == "Bob"
        profile.device.get_profiles = list  # machine answers nothing
        await profile.async_refresh_state()
        assert profile.options == ["Alice", "Bob"]
        assert profile.current_option == "Bob"
        assert profile.extra_state_attributes == {"profile_index": 2}

    async def test_live_selection_wins_over_restored_state(self, hass):
        profile = await self._profile(
            hass, _Last("Bob", {"profile_index": 2}), current=1
        )
        assert profile.current_option == "Alice"
        assert profile.device.current_profile == 1


class TestSelectTranslations:
    async def test_every_water_hardness_option_is_translated(self, hass):
        options = set(SETTING_OPTION_MAPS["water_hardness"].options.values())
        for lang in ("en", "de"):
            data = json.loads((TRANSLATIONS / f"{lang}.json").read_text())
            states = data["entity"]["select"]["setting_water_hardness"]["state"]
            assert options == set(states), lang

    async def test_water_hardness_select_uses_the_translation_key(self, hass):
        _, entities = await _setup(
            hass, select_mod, FakeMonitorData(status_name="ready")
        )
        select = _by_uid(entities, "entry1_setting_water_hardness")
        assert select.translation_key == "setting_water_hardness"
