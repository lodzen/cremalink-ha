"""Profile select entity: occupied-slot options + acked-state tracking (T030)."""

import pytest
from cremalink.ecam.profiles import ProfileSlot
from custom_components.cremalink_ha import select as select_mod

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)


def _slots(*pairs):
    return [ProfileSlot(index=i, name=n, icon=0) for i, n in pairs]


async def _setup(hass, **dev):
    entry = make_entry()
    device = make_device(**dev)
    monitor = FakeMonitorData(status_name="ready")
    return await setup_entities(hass, entry, device, select_mod, monitor)


class TestProfileSelect:
    async def test_options_from_occupied_slots(self, hass):
        _, entities = await _setup(
            hass, get_profiles=lambda: _slots((1, "Alice"), (2, "Bob"), (3, "Profil 3"))
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.options == ["Alice", "Bob", "Profil 3"]

    async def test_empty_slots_no_options(self, hass):
        _, entities = await _setup(hass, get_profiles=list)
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.options == []
        assert profile.current_option is None

    async def test_select_sends_index_and_tracks_acked(self, hass):
        sent = []
        device_state = {"current": 0}

        def _select(index):
            sent.append(index)
            device_state["current"] = index
            return True

        _, entities = await _setup(
            hass,
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            select_profile=_select,
            current_profile=0,
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        await profile.async_select_option("Bob")
        assert sent == [2]
        assert profile.current_option == "Bob"

    async def test_failed_ack_keeps_previous_option(self, hass):
        _, entities = await _setup(
            hass,
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            select_profile=lambda index: False,
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        profile._current_option = "Alice"
        await profile.async_select_option("Bob")
        assert profile.current_option == "Alice"

    async def test_unknown_option_raises(self, hass):
        _, entities = await _setup(hass, get_profiles=lambda: _slots((1, "Alice")))
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        try:
            await profile.async_select_option("Nope")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")

    async def test_startup_state_unknown_until_acked(self, hass):
        # current_profile=0 (no selection yet) → unknown even with slots.
        _, entities = await _setup(
            hass, get_profiles=lambda: _slots((1, "Alice")), current_profile=0
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.current_option is None

    async def test_refresh_maps_current_profile_to_option(self, hass):
        _, entities = await _setup(
            hass,
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            current_profile=2,
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.current_option == "Bob"

    async def test_machine_read_profile_updates_option_on_coordinator_update(
        self, hass
    ):
        # The coordinator's param-0x03EE refresh lands in
        # device.current_profile; an update must re-map the option (T055).
        _, entities = await _setup(
            hass,
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            current_profile=1,
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.current_option == "Alice"
        profile.device.current_profile = 2
        profile._handle_coordinator_update()
        assert profile.current_option == "Bob"

    @pytest.mark.parametrize(
        "status", ["in_standby", "going_to_sleep", "sleeping", "waking_up"]
    )
    async def test_profile_select_unavailable_in_not_ready_states(self, status, hass):
        # Observed behaviour of the official app: profile selection is the
        # only setting unavailable while the machine is asleep — config
        # settings (beep, energy, …) stay available (see switch tests).
        device = make_device(
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            current_profile=1,
        )
        monitor = FakeMonitorData(status_name=status)
        _, entities = await setup_entities(
            hass, make_entry(), device, select_mod, monitor
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.available is False
        monitor.status_name = "ready"
        profile._handle_coordinator_update()
        assert profile.available is True
