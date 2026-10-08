"""Entity organisation: categories, Stop availability, bit sensors, wake refresh."""

import asyncio
import json
from pathlib import Path

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
    FakeEntry,
    FakeHass,
    FakeMonitorData,
    make_device,
    setup_entities,
)

TRANSLATIONS = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "cremalink_ha"
    / "translations"
)


def _setup(module, monitor, **dev):
    hass = FakeHass()
    device = make_device(**dev)
    device.get_commands = lambda: ["espresso", "stop", "wakeup"]
    coordinator, entities = setup_entities(hass, FakeEntry(), device, module, monitor)
    return hass, coordinator, entities


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
    def test_unavailable_in_standby_even_with_latched_action(self):
        monitor = FakeMonitorData(status_name="in_standby", is_busy=True)
        _, _, entities = _setup(button_mod, monitor)
        assert _by_uid(entities, "entry1_cmd_stop").available is False

    def test_availability_does_not_follow_the_action_byte(self):
        busy = FakeMonitorData(status_name="ready", is_busy=True)
        _, coordinator, entities = _setup(button_mod, busy)
        stop = _by_uid(entities, "entry1_cmd_stop")
        assert stop.available is True
        coordinator.data = FakeMonitorData(status_name="ready", is_busy=False)
        assert stop.available is True

    def test_stop_is_always_sent_when_awake(self):
        calls = []
        _, _, entities = _setup(
            button_mod,
            FakeMonitorData(status_name="ready", is_busy=False),
            do=calls.append,
        )
        asyncio.run(_by_uid(entities, "entry1_cmd_stop").async_press())
        assert calls == ["stop"]


class TestBrewButtons:
    def test_unavailable_whenever_the_machine_is_not_awake(self):
        _, coordinator, entities = _setup(
            button_mod, FakeMonitorData(status_name="ready", is_busy=False)
        )
        espresso = _by_uid(entities, "entry1_cmd_espresso")
        for status in ("in_standby", "going_to_sleep", "waking_up"):
            coordinator.data = FakeMonitorData(status_name=status, is_busy=False)
            assert espresso.available is False, status
        coordinator.data = FakeMonitorData(status_name="ready", is_busy=False)
        assert espresso.available is True

    def test_availability_ignores_the_action_byte(self):
        _, coordinator, entities = _setup(
            button_mod, FakeMonitorData(status_name="ready", is_busy=False)
        )
        espresso = _by_uid(entities, "entry1_cmd_espresso")
        for busy in (False, True, False, True):
            coordinator.data = FakeMonitorData(status_name="ready", is_busy=busy)
            assert espresso.available is True

    def test_press_when_ready_brews(self):
        calls = []
        _, _, entities = _setup(
            button_mod,
            FakeMonitorData(status_name="ready", is_busy=False),
            do=calls.append,
        )
        asyncio.run(_by_uid(entities, "entry1_cmd_espresso").async_press())
        assert calls == ["espresso"]

    def test_press_is_rejected_when_busy_or_not_ready(self):
        calls = []
        for status, busy in (
            ("ready", True),
            ("in_standby", False),
            ("waking_up", False),
        ):
            _, _, entities = _setup(
                button_mod,
                FakeMonitorData(status_name=status, is_busy=busy),
                do=calls.append,
            )
            with pytest.raises(HomeAssistantError):
                asyncio.run(_by_uid(entities, "entry1_cmd_espresso").async_press())
        assert calls == []


class TestEntityCategories:
    def test_setting_selects_are_config(self):
        _, _, entities = _setup(select_mod, FakeMonitorData(status_name="ready"))
        assert {e.unique_id for e in entities} >= {
            "entry1_profile",
            "entry1_setting_auto_off",
            "entry1_setting_water_hardness",
        }
        for entity in entities:
            assert entity.entity_category == EntityCategory.CONFIG

    def test_monitor_sensors_diagnostic_statistics_not(self):
        _, _, entities = _setup(sensor_mod, FakeMonitorData(status_name="ready"))
        for uid in ("status_name", "progress_percent", "accessory_name", "action_code"):
            assert _by_uid(entities, f"entry1_{uid}").entity_category == (
                EntityCategory.DIAGNOSTIC
            )
        stats = [e for e in entities if "_stat_" in e.unique_id]
        assert stats
        assert all(e.entity_category is None for e in stats)

    def test_binary_sensors_all_diagnostic(self):
        _, _, entities = _setup(bs_mod, FakeMonitorData(status_name="ready"))
        assert entities
        for entity in entities:
            assert entity.entity_category == EntityCategory.DIAGNOSTIC


class TestBitSensors:
    def test_one_entity_per_documented_bit_with_unique_names(self):
        _, _, entities = _setup(bs_mod, _View(status_name="ready"))
        bit_uids = {
            e.unique_id
            for e in entities
            if e.unique_id.split("_", 1)[1][:6] in ("switch", "alarm_")
        }
        assert len(bit_uids) == len(SWITCH_BITS) + len(ALARM_BITS)
        names = [e.name for e in entities]
        assert len(names) == len(set(names))

    def test_clean_knob_and_motor_position_follow_the_frame(self):
        monitor = _View(
            status_name="ready",
            switches={"clean_knob": True, "motor_up": True, "motor_down": False},
        )
        _, coordinator, entities = _setup(bs_mod, monitor)
        assert _by_uid(entities, "entry1_switch_clean_knob").is_on is True
        assert _by_uid(entities, "entry1_switch_motor_up").is_on is True
        assert _by_uid(entities, "entry1_switch_motor_down").is_on is False
        coordinator.data = _View(status_name="ready", alarms={"descale": True})
        assert _by_uid(entities, "entry1_alarm_descale").is_on is True

    def test_standby_keeps_last_live_reading(self):
        _, coordinator, entities = _setup(
            bs_mod, _View(status_name="ready", alarms={"descale": False})
        )
        sensor = _by_uid(entities, "entry1_alarm_descale")
        assert sensor.is_on is False
        # Latched bit in a standby frame must not surface.
        coordinator.data = _View(status_name="in_standby", alarms={"descale": True})
        assert sensor.is_on is False

    def test_rare_hardware_faults_disabled_by_default(self):
        _, _, entities = _setup(bs_mod, _View(status_name="ready"))
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

    def test_profile_names_reread_when_machine_wakes(self):
        names = ["Alice"]
        hass, coordinator, entities = _setup(
            select_mod,
            FakeMonitorData(status_name="in_standby"),
            get_profiles=lambda: self._profiles(names)(),
        )
        profile = _by_uid(entities, "entry1_profile")
        profile.hass = hass
        profile.async_write_ha_state = lambda: None
        assert profile.options == ["Alice"]

        profile._handle_coordinator_update()  # still asleep: nothing scheduled
        assert hass.tasks == []

        names.append("Bob")  # renamed/added on the machine meanwhile
        coordinator.data = FakeMonitorData(status_name="ready")
        profile._handle_coordinator_update()
        assert len(hass.tasks) == 1
        asyncio.run(hass.tasks.pop())
        assert profile.options == ["Alice", "Bob"]

    def test_waking_up_status_does_not_refresh_yet(self):
        hass, coordinator, entities = _setup(
            select_mod, FakeMonitorData(status_name="in_standby")
        )
        profile = _by_uid(entities, "entry1_profile")
        profile.hass = hass
        profile.async_write_ha_state = lambda: None
        profile._handle_coordinator_update()
        coordinator.data = FakeMonitorData(status_name="waking_up")
        profile._handle_coordinator_update()
        assert hass.tasks == []

    def test_no_refresh_when_already_awake(self):
        hass, _, entities = _setup(select_mod, FakeMonitorData(status_name="ready"))
        profile = _by_uid(entities, "entry1_profile")
        profile.hass = hass
        profile.async_write_ha_state = lambda: None
        profile._handle_coordinator_update()
        profile._handle_coordinator_update()
        assert hass.tasks == []


class TestCleanNames:
    def test_no_entity_name_carries_the_device_title(self):
        for module in (sensor_mod, bs_mod, select_mod, button_mod, switch_mod):
            _, _, entities = _setup(module, _View(status_name="ready"))
            assert entities
            for entity in entities:
                assert "Soul" not in entity.name, (module.__name__, entity.name)

    def test_expected_clean_names(self):
        _, _, sensors = _setup(sensor_mod, FakeMonitorData(status_name="ready"))
        assert _by_uid(sensors, "entry1_action_code").name == "Action Code"
        _, _, selects = _setup(select_mod, FakeMonitorData(status_name="ready"))
        assert _by_uid(selects, "entry1_profile").name == "Profile"
        assert _by_uid(selects, "entry1_setting_auto_off").name == "Auto-Off"
        assert (
            _by_uid(selects, "entry1_setting_water_hardness").name == "Water Hardness"
        )


class _Last:
    """A stored entity state, as ``RestoreEntity.async_get_last_state`` returns."""

    def __init__(self, state, attributes):
        self.state, self.attributes = state, attributes


class TestProfileRestore:
    def _profile(self, last, current=0):
        _, _, entities = _setup(
            select_mod,
            FakeMonitorData(status_name="ready"),
            get_profiles=lambda: [
                ProfileSlot(index=1, name="Alice", icon=0),
                ProfileSlot(index=2, name="Bob", icon=0),
            ],
            current_profile=current,
        )
        profile = _by_uid(entities, "entry1_profile")
        profile._last_state = last
        return profile

    def test_last_selection_survives_a_restart(self):
        profile = self._profile(_Last("Bob", {"profile_index": 2}))
        asyncio.run(profile.async_added_to_hass())  # slots loaded at setup
        assert profile.current_option == "Bob"
        assert profile.device.current_profile == 2  # brews use it too
        assert profile.extra_state_attributes == {"profile_index": 2}

    def test_restore_before_slots_are_read_applies_after_refresh(self):
        profile = self._profile(_Last("Bob", {"profile_index": 2}))
        profile._slots = {}
        profile._current_option = None
        asyncio.run(profile.async_added_to_hass())
        assert profile.current_option is None  # nothing to map onto yet
        profile.hass = FakeHass()
        asyncio.run(profile.async_refresh_state())
        assert profile.current_option == "Bob"

    def test_missing_or_vanished_profile_stays_unknown(self):
        for last in (None, _Last("unknown", {}), _Last("Zed", {"profile_index": 5})):
            profile = self._profile(last)
            asyncio.run(profile.async_added_to_hass())
            assert profile.current_option is None
            assert profile.device.current_profile == 0

    def test_selection_forces_a_restore_state_flush(self):
        from homeassistant.helpers.restore_state import RestoreStateData

        profile = self._profile(None)
        # The real library records the profile when the 0xA9 ack arrives.
        profile.device.select_profile = lambda index: (
            setattr(profile.device, "current_profile", index) or True
        )
        before = RestoreStateData.dumps
        asyncio.run(profile.async_select_option("Bob"))
        assert RestoreStateData.dumps == before + 1
        assert profile.extra_state_attributes == {"profile_index": 2}

    def test_attribute_survives_an_empty_slot_read(self):
        profile = self._profile(None, current=2)
        assert profile.current_option == "Bob"
        profile.device.get_profiles = list  # machine answers nothing
        asyncio.run(profile.async_refresh_state())
        assert profile.options == ["Alice", "Bob"]
        assert profile.current_option == "Bob"
        assert profile.extra_state_attributes == {"profile_index": 2}

    def test_live_selection_wins_over_restored_state(self):
        profile = self._profile(_Last("Bob", {"profile_index": 2}), current=1)
        asyncio.run(profile.async_added_to_hass())
        assert profile.current_option == "Alice"
        assert profile.device.current_profile == 1


class TestSelectTranslations:
    def test_every_water_hardness_option_is_translated(self):
        options = set(SETTING_OPTION_MAPS["water_hardness"].options.values())
        for lang in ("en", "de"):
            data = json.loads((TRANSLATIONS / f"{lang}.json").read_text())
            states = data["entity"]["select"]["setting_water_hardness"]["state"]
            assert options == set(states), lang

    def test_water_hardness_select_uses_the_translation_key(self):
        _, _, entities = _setup(select_mod, FakeMonitorData(status_name="ready"))
        select = _by_uid(entities, "entry1_setting_water_hardness")
        assert select.translation_key == "setting_water_hardness"
