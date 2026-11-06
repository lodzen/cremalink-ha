"""Setting selects: option maps, gated writes, confirmed-state only (T035)."""

import asyncio

import pytest
from custom_components.cremalink_ha import select as select_mod
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
    return setup_entities(hass, entry, device, select_mod, monitor)


def _by_uid(entities, uid):
    return next(e for e in entities if e.unique_id == uid)


class TestAutoOff:
    def test_options_in_map_order(self):
        _, entities = _setup()
        sel = _by_uid(entities, "entry1_setting_auto_off")
        assert sel.options == ["15 min", "30 min", "1 h", "3 h"]

    def test_current_from_machine_read(self):
        _, entities = _setup(get_settings=lambda **_: {"auto_off": 2})
        sel = _by_uid(entities, "entry1_setting_auto_off")
        assert sel.current_option == "1 h"

    def test_select_writes_index_and_confirms(self):
        writes = []

        def _set(key, index):
            writes.append((key, index))
            return True

        _, entities = _setup(set_setting=_set)
        sel = _by_uid(entities, "entry1_setting_auto_off")
        asyncio.run(sel.async_select_option("3 h"))
        assert writes == [("auto_off", 3)]
        assert sel.current_option == "3 h"

    def test_failed_write_keeps_previous_option(self):
        _, entities = _setup(set_setting=lambda key, idx: False)
        sel = _by_uid(entities, "entry1_setting_auto_off")
        sel._current_option = "15 min"
        with pytest.raises(HomeAssistantError):
            asyncio.run(sel.async_select_option("3 h"))
        assert sel.current_option == "15 min"

    @pytest.mark.parametrize("status", ["in_standby", "going_to_sleep", "waking_up"])
    def test_setting_write_is_attempted_in_standby(self, status):
        # Config changes work while the machine is asleep — the machine
        # processes data_request in standby and the app exposes these
        # settings there; only profile selection is unavailable.
        writes = []
        hass = FakeHass()
        device = make_device(set_setting=lambda key, idx: writes.append(key) or True)
        monitor = FakeMonitorData(status_name=status)
        _, entities = setup_entities(hass, FakeEntry(), device, select_mod, monitor)
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        sel._current_option = "level_1"
        asyncio.run(sel.async_select_option("level_3"))
        assert writes == ["water_hardness"]
        assert sel.current_option == "level_3"

    def test_unconfirmed_write_is_a_clean_user_error(self):
        def _timeout(key, idx):
            raise TimeoutError("no confirmation")

        _, entities = _setup(set_setting=_timeout)
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        sel._current_option = "level_1"
        with pytest.raises(HomeAssistantError, match="did not confirm"):
            asyncio.run(sel.async_select_option("level_3"))
        assert sel.current_option == "level_1"

    def test_unknown_option_raises(self):
        _, entities = _setup()
        sel = _by_uid(entities, "entry1_setting_auto_off")
        try:
            asyncio.run(sel.async_select_option("2 h"))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


class TestWaterHardness:
    def test_levels_displayed_one_based(self):
        _, entities = _setup()
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        assert sel.options == ["level_1", "level_2", "level_3", "level_4"]

    def test_raw_index_maps_to_level(self):
        _, entities = _setup(get_settings=lambda **_: {"water_hardness": 0})
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        assert sel.current_option == "level_1"

    def test_out_of_map_raw_index_unknown(self):
        _, entities = _setup(get_settings=lambda **_: {"water_hardness": 9})
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        assert sel.current_option is None

    def test_select_writes_zero_based_index(self):
        writes = []
        _, entities = _setup(
            set_setting=lambda key, idx: writes.append((key, idx)) or True
        )
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        asyncio.run(sel.async_select_option("level_3"))
        assert writes == [("water_hardness", 2)]


class TestCapabilityGating:
    def test_unsupported_capability_creates_no_select(self):
        _, entities = _setup(
            capabilities={
                "auto_off_settings": False,
                "water_hardness_settings": True,
            }
        )
        uids = {e.unique_id for e in entities}
        assert "entry1_setting_auto_off" not in uids
        assert "entry1_setting_water_hardness" in uids


class TestCoordinatorTracking:
    def test_panel_side_change_tracked_via_coordinator(self):
        """§14.11: panel edits republish the dNNN — coordinator.settings
        drives the entity between own writes."""
        _, entities = _setup(get_settings=lambda **_: {"auto_off": 2})
        sel = _by_uid(entities, "entry1_setting_auto_off")
        assert sel.current_option == "1 h"
        sel.coordinator.settings = {"auto_off": 0}
        sel._handle_coordinator_update()
        assert sel.current_option == "15 min"

    def test_unmapped_value_does_not_clobber_known_option(self):
        _, entities = _setup(get_settings=lambda **_: {"auto_off": 2})
        sel = _by_uid(entities, "entry1_setting_auto_off")
        sel.coordinator.settings = {"auto_off": None}
        sel._handle_coordinator_update()
        assert sel.current_option == "1 h"

    def test_confirmed_select_survives_stale_coordinator_snapshot(self):
        """§14.11: a confirmed select patches the tracked snapshot, so a
        pre-write coordinator value must not flap the option back."""
        _, entities = _setup(
            get_settings=lambda **_: {"auto_off": 2},
            set_setting=lambda key, idx: True,
        )
        sel = _by_uid(entities, "entry1_setting_auto_off")
        sel.coordinator.settings = {"auto_off": 2}
        asyncio.run(sel.async_select_option("15 min"))
        sel._handle_coordinator_update()
        assert sel.current_option == "15 min"
