"""Setting selects: option maps, gated writes, confirmed-state only (T035)."""

import pytest
from custom_components.cremalink_ha import select as select_mod
from homeassistant.exceptions import HomeAssistantError

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)


async def _setup(hass, **dev):
    entry = make_entry()
    device = make_device(**dev)
    monitor = FakeMonitorData(status_name="ready")
    return await setup_entities(hass, entry, device, select_mod, monitor)


def _by_uid(entities, uid):
    return next(e for e in entities if e.unique_id == uid)


class TestAutoOff:
    async def test_options_in_map_order(self, hass):
        _, entities = await _setup(hass)
        sel = _by_uid(entities, "entry1_setting_auto_off")
        assert sel.options == ["15 min", "30 min", "1 h", "3 h"]

    async def test_current_from_machine_read(self, hass):
        _, entities = await _setup(hass, get_settings=lambda **_: {"auto_off": 2})
        sel = _by_uid(entities, "entry1_setting_auto_off")
        assert sel.current_option == "1 h"

    async def test_select_writes_index_and_confirms(self, hass):
        writes = []

        def _set(key, index):
            writes.append((key, index))
            return True

        _, entities = await _setup(hass, set_setting=_set)
        sel = _by_uid(entities, "entry1_setting_auto_off")
        await sel.async_select_option("3 h")
        assert writes == [("auto_off", 3)]
        assert sel.current_option == "3 h"

    async def test_failed_write_keeps_previous_option(self, hass):
        _, entities = await _setup(hass, set_setting=lambda key, idx: False)
        sel = _by_uid(entities, "entry1_setting_auto_off")
        sel._current_option = "15 min"
        with pytest.raises(HomeAssistantError):
            await sel.async_select_option("3 h")
        assert sel.current_option == "15 min"

    @pytest.mark.parametrize("status", ["in_standby", "going_to_sleep", "waking_up"])
    async def test_setting_write_is_attempted_in_standby(self, status, hass):
        # Config changes work while the machine is asleep — the machine
        # processes data_request in standby and the app exposes these
        # settings there; only profile selection is unavailable.
        writes = []
        device = make_device(set_setting=lambda key, idx: writes.append(key) or True)
        monitor = FakeMonitorData(status_name=status)
        _, entities = await setup_entities(
            hass, make_entry(), device, select_mod, monitor
        )
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        sel._current_option = "level_1"
        await sel.async_select_option("level_3")
        assert writes == ["water_hardness"]
        assert sel.current_option == "level_3"

    async def test_unconfirmed_write_is_a_clean_user_error(self, hass):
        def _timeout(key, idx):
            raise TimeoutError("no confirmation")

        _, entities = await _setup(hass, set_setting=_timeout)
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        sel._current_option = "level_1"
        with pytest.raises(HomeAssistantError, match="did not confirm"):
            await sel.async_select_option("level_3")
        assert sel.current_option == "level_1"

    async def test_unknown_option_raises(self, hass):
        _, entities = await _setup(hass)
        sel = _by_uid(entities, "entry1_setting_auto_off")
        try:
            await sel.async_select_option("2 h")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


class TestWaterHardness:
    async def test_levels_displayed_one_based(self, hass):
        _, entities = await _setup(hass)
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        assert sel.options == ["level_1", "level_2", "level_3", "level_4"]

    async def test_raw_index_maps_to_level(self, hass):
        _, entities = await _setup(hass, get_settings=lambda **_: {"water_hardness": 0})
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        assert sel.current_option == "level_1"

    async def test_out_of_map_raw_index_unknown(self, hass):
        _, entities = await _setup(hass, get_settings=lambda **_: {"water_hardness": 9})
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        assert sel.current_option is None

    async def test_select_writes_zero_based_index(self, hass):
        writes = []
        _, entities = await _setup(
            hass, set_setting=lambda key, idx: writes.append((key, idx)) or True
        )
        sel = _by_uid(entities, "entry1_setting_water_hardness")
        await sel.async_select_option("level_3")
        assert writes == [("water_hardness", 2)]


class TestCapabilityGating:
    async def test_unsupported_capability_creates_no_select(self, hass):
        _, entities = await _setup(
            hass,
            capabilities={
                "auto_off_settings": False,
                "water_hardness_settings": True,
            },
        )
        uids = {e.unique_id for e in entities}
        assert "entry1_setting_auto_off" not in uids
        assert "entry1_setting_water_hardness" in uids


class TestCoordinatorTracking:
    async def test_panel_side_change_tracked_via_coordinator(self, hass):
        """§14.11: panel edits republish the dNNN — coordinator.settings
        drives the entity between own writes."""
        _, entities = await _setup(hass, get_settings=lambda **_: {"auto_off": 2})
        sel = _by_uid(entities, "entry1_setting_auto_off")
        assert sel.current_option == "1 h"
        sel.coordinator.settings = {"auto_off": 0}
        sel._handle_coordinator_update()
        assert sel.current_option == "15 min"

    async def test_unmapped_value_does_not_clobber_known_option(self, hass):
        _, entities = await _setup(hass, get_settings=lambda **_: {"auto_off": 2})
        sel = _by_uid(entities, "entry1_setting_auto_off")
        sel.coordinator.settings = {"auto_off": None}
        sel._handle_coordinator_update()
        assert sel.current_option == "1 h"

    async def test_confirmed_select_survives_stale_coordinator_snapshot(self, hass):
        """§14.11: a confirmed select patches the tracked snapshot, so a
        pre-write coordinator value must not flap the option back."""
        _, entities = await _setup(
            hass,
            get_settings=lambda **_: {"auto_off": 2},
            set_setting=lambda key, idx: True,
        )
        sel = _by_uid(entities, "entry1_setting_auto_off")
        sel.coordinator.settings = {"auto_off": 2}
        await sel.async_select_option("15 min")
        sel._handle_coordinator_update()
        assert sel.current_option == "15 min"
