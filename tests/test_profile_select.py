"""Profile select entity: occupied-slot options + acked-state tracking (T030)."""

import asyncio

from cremalink.ecam.profiles import ProfileSlot
from custom_components.cremalink_ha import select as select_mod

from tests.helpers import (
    FakeEntry,
    FakeHass,
    FakeMonitorData,
    make_device,
    setup_entities,
)


def _slots(*pairs):
    return [ProfileSlot(index=i, name=n, icon=0) for i, n in pairs]


def _setup(**dev):
    hass = FakeHass()
    entry = FakeEntry()
    device = make_device(**dev)
    monitor = FakeMonitorData(status_name="ready")
    return setup_entities(hass, entry, device, select_mod, monitor)


class TestProfileSelect:
    def test_options_from_occupied_slots(self):
        _, entities = _setup(
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob"), (3, "Profil 3"))
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.options == ["Alice", "Bob", "Profil 3"]

    def test_empty_slots_no_options(self):
        _, entities = _setup(get_profiles=list)
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.options == []
        assert profile.current_option is None

    def test_select_sends_index_and_tracks_acked(self):
        sent = []
        device_state = {"current": 0}

        def _select(index):
            sent.append(index)
            device_state["current"] = index
            return True

        _, entities = _setup(
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            select_profile=_select,
            current_profile=0,
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        asyncio.run(profile.async_select_option("Bob"))
        assert sent == [2]
        assert profile.current_option == "Bob"

    def test_failed_ack_keeps_previous_option(self):
        _, entities = _setup(
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            select_profile=lambda index: False,
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        profile._current_option = "Alice"
        asyncio.run(profile.async_select_option("Bob"))
        assert profile.current_option == "Alice"

    def test_unknown_option_raises(self):
        _, entities = _setup(get_profiles=lambda: _slots((1, "Alice")))
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        try:
            asyncio.run(profile.async_select_option("Nope"))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")

    def test_startup_state_unknown_until_acked(self):
        # current_profile=0 (no selection yet) → unknown even with slots.
        _, entities = _setup(
            get_profiles=lambda: _slots((1, "Alice")), current_profile=0
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.current_option is None

    def test_refresh_maps_current_profile_to_option(self):
        _, entities = _setup(
            get_profiles=lambda: _slots((1, "Alice"), (2, "Bob")),
            current_profile=2,
        )
        profile = next(e for e in entities if e.unique_id == "entry1_profile")
        assert profile.current_option == "Bob"
