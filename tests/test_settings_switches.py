"""Param-63 bitmask switches: beep + energy saving, CONFIG entities (T058)."""

import asyncio

import pytest
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


def _setup(**dev):
    hass = FakeHass()
    entry = FakeEntry()
    device = make_device(**dev)
    monitor = FakeMonitorData(status_name="ready")
    return setup_entities(hass, entry, device, switch_mod, monitor)


def _by_uid(entities, uid):
    return next(e for e in entities if e.unique_id == uid)


class TestEntities:
    def test_power_and_both_setting_switches_created(self):
        _, entities = _setup()
        uids = {e.unique_id for e in entities}
        assert uids == {
            "entry1_power",
            "entry1_setting_beep",
            "entry1_setting_energy_saving",
        }

    def test_setting_switches_are_config_power_is_control(self):
        _, entities = _setup()
        assert _by_uid(entities, "entry1_power").entity_category is None
        for uid in ("entry1_setting_beep", "entry1_setting_energy_saving"):
            entity = _by_uid(entities, uid)
            assert entity.entity_category == EntityCategory.CONFIG
            assert entity.has_entity_name is True

    def test_names_come_from_translations(self):
        _, entities = _setup()
        assert _by_uid(entities, "entry1_setting_beep").name == "Beep"
        assert _by_uid(entities, "entry1_setting_energy_saving").name == "Energy Saving"

    def test_capability_gating(self):
        _, entities = _setup(
            capabilities={
                "buzzer_settings": False,
                "energy_saving_settings": True,
            }
        )
        uids = {e.unique_id for e in entities}
        assert "entry1_setting_beep" not in uids
        assert "entry1_setting_energy_saving" in uids


class TestState:
    def test_state_primed_from_machine_read(self):
        _, entities = _setup(
            get_setting_bits=lambda **_: {"beep": True, "energy_saving": False}
        )
        assert _by_uid(entities, "entry1_setting_beep").is_on is True
        assert _by_uid(entities, "entry1_setting_energy_saving").is_on is False

    def test_unreadable_param_is_unknown_not_off(self):
        _, entities = _setup(
            get_setting_bits=lambda **_: {"beep": None, "energy_saving": None}
        )
        assert _by_uid(entities, "entry1_setting_beep").is_on is None

    def test_panel_side_change_tracked_via_coordinator(self):
        """§14.11: panel edits republish d284 — coordinator.setting_bits
        drives the entity between own writes."""
        hass, entities = _setup(get_setting_bits=lambda **_: {"beep": True})
        switch = _by_uid(entities, "entry1_setting_beep")
        assert switch.is_on is True
        switch.coordinator.setting_bits = {"beep": False}
        switch._handle_coordinator_update()
        assert switch.is_on is False

    def test_none_bit_does_not_clobber_known_state(self):
        _, entities = _setup(get_setting_bits=lambda **_: {"beep": True})
        switch = _by_uid(entities, "entry1_setting_beep")
        switch.coordinator.setting_bits = {"beep": None}
        switch._handle_coordinator_update()
        assert switch.is_on is True


class TestWrites:
    def test_turn_on_calls_set_setting_bit(self):
        calls = []
        _, entities = _setup(
            get_setting_bits=lambda **_: {"beep": False},
            set_setting_bit=lambda key, on: calls.append((key, on)) or True,
        )
        switch = _by_uid(entities, "entry1_setting_beep")
        asyncio.run(switch.async_turn_on())
        assert calls == [("beep", True)]
        assert switch.is_on is True

    def test_confirmed_write_survives_stale_coordinator_snapshot(self):
        """§14.11: a confirmed write patches the tracked snapshot, so a
        pre-write coordinator value must not flap the switch back."""
        _, entities = _setup(
            get_setting_bits=lambda **_: {"beep": False},
            set_setting_bit=lambda key, on: True,
        )
        switch = _by_uid(entities, "entry1_setting_beep")
        switch.coordinator.setting_bits = {"beep": False}
        asyncio.run(switch.async_turn_on())
        switch._handle_coordinator_update()
        assert switch.is_on is True

    def test_turn_off_calls_set_setting_bit(self):
        calls = []
        _, entities = _setup(
            get_setting_bits=lambda **_: {"energy_saving": True},
            set_setting_bit=lambda key, on: calls.append((key, on)) or True,
        )
        switch = _by_uid(entities, "entry1_setting_energy_saving")
        asyncio.run(switch.async_turn_off())
        assert calls == [("energy_saving", False)]
        assert switch.is_on is False

    def test_failed_write_keeps_previous_state(self):
        _, entities = _setup(
            get_setting_bits=lambda **_: {"beep": True},
            set_setting_bit=lambda key, on: False,
        )
        switch = _by_uid(entities, "entry1_setting_beep")
        with pytest.raises(HomeAssistantError):
            asyncio.run(switch.async_turn_off())
        assert switch.is_on is True

    def test_unconfirmed_write_is_a_clean_user_error(self):
        def _timeout(key, on):
            raise TimeoutError("no confirmation")

        _, entities = _setup(
            get_setting_bits=lambda **_: {"beep": True},
            set_setting_bit=_timeout,
        )
        switch = _by_uid(entities, "entry1_setting_beep")
        with pytest.raises(HomeAssistantError, match="did not confirm"):
            asyncio.run(switch.async_turn_off())
        assert switch.is_on is True

    @pytest.mark.parametrize("status", ["in_standby", "going_to_sleep", "waking_up"])
    def test_setting_write_is_attempted_in_standby(self, status):
        # Config changes work while the machine is asleep — the machine
        # processes data_request in standby and the app exposes these
        # toggles there; only profile selection is unavailable (see the
        # profile select test).
        calls = []
        hass = FakeHass()
        device = make_device(
            get_setting_bits=lambda **_: {"beep": True},
            set_setting_bit=lambda key, on: calls.append(key) or True,
        )
        monitor = FakeMonitorData(status_name=status)
        _, entities = setup_entities(hass, FakeEntry(), device, switch_mod, monitor)
        switch = _by_uid(entities, "entry1_setting_beep")
        asyncio.run(switch.async_turn_off())
        assert calls == ["beep"]
        assert switch.is_on is False
