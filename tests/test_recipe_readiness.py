"""US5: params + brew stay disabled until data for the current
``(recipe, profile)`` pair is loaded.

``RecipeSession.ready`` gates both the number/brew-switch availability
and — because ``available`` is UI-only — their service paths with a hard
``HomeAssistantError``. The window it closes: ``_profile_changed`` only
clears ``params`` inside ``async_ensure_params``; a profile change
between cycles would otherwise leave stale-profile values usable.
"""

import pytest
from cremalink.domain.device import RecipeParams
from homeassistant.exceptions import HomeAssistantError

from custom_components.cremalink_ha import number as number_mod
from custom_components.cremalink_ha import switch as switch_mod
from custom_components.cremalink_ha.recipe_session import RecipeSession

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)


def _params(bev_id=0x01, profile=1):
    return RecipeParams(
        beverage_id=bev_id,
        profile_slot=profile,
        values={1: 60, 2: 3},
        bounds={1: (30, 40, 60), 2: (1, 3, 5), 24: (0, 1, 1)},
        source="stored",
    )


def _session(**dev):
    return RecipeSession(make_device(**dev))


class TestSessionReady:
    def test_no_selection_not_ready(self):
        assert _session().ready is False

    def test_selected_without_params_not_ready(self):
        session = _session()
        session.select(0x01)
        assert session.ready is False

    def test_loading_not_ready(self):
        session = _session()
        session.select(0x01)
        session.params = _params()
        session.loading = True
        assert session.ready is False

    def test_beverage_mismatch_not_ready(self):
        session = _session()
        session.select(0x08)
        session.params = _params(bev_id=0x01)
        assert session.ready is False

    def test_profile_drift_not_ready(self):
        # Params stamped for profile 1 while the machine sits on 2 —
        # stale values must not read as ready before ensure clears them.
        session = _session(current_profile=2)
        session.select(0x01)
        session.params = _params(profile=1)
        assert session.ready is False

    def test_unasserted_profile_resolves_to_slot_1(self):
        # ``current_profile == 0`` (no 0xA9 acked yet) brews under slot
        # 1 — the same ``or 1`` resolution recipe_params/brew apply.
        session = _session(current_profile=0)
        session.select(0x01)
        session.params = _params(profile=1)
        assert session.ready is True

    def test_matching_pair_ready(self):
        session = _session(current_profile=2)
        session.select(0x01)
        session.params = _params(profile=2)
        assert session.ready is True


async def _setup(platform_mod, hass, **dev):
    entry = make_entry()
    device = make_device(**dev)
    coordinator, entities = await setup_entities(
        hass, entry, device, platform_mod, FakeMonitorData(status_name="ready")
    )
    session = hass.data["cremalink_ha"][entry.entry_id]["recipe_session"]
    return coordinator, entities, session, device


def _param(entities, param_id):
    return next(e for e in entities if e.unique_id == f"entry1_recipe_param_{param_id}")


def _brew_switch(entities):
    return next(e for e in entities if e.unique_id == "entry1_brew_recipe")


class TestNumberReadiness:
    async def test_unavailable_on_profile_drift(self, hass):
        _, entities, session, device = await _setup(number_mod, hass, current_profile=1)
        session.select(0x01)
        session.params = _params(profile=1)
        assert _param(entities, 1).available is True
        device.current_profile = 2  # panel-side profile switch
        assert _param(entities, 1).available is False

    async def test_set_value_raises_when_not_ready(self, hass):
        _, entities, session, _ = await _setup(number_mod, hass)
        session.select(0x01)  # selected, nothing loaded
        with pytest.raises(HomeAssistantError):
            await _param(entities, 1).async_set_native_value(50)

    async def test_set_value_raises_on_profile_drift(self, hass):
        _, entities, session, device = await _setup(number_mod, hass, current_profile=1)
        session.select(0x01)
        session.params = _params(profile=1)
        device.current_profile = 2
        with pytest.raises(HomeAssistantError):
            await _param(entities, 1).async_set_native_value(50)

    async def test_available_again_after_reload(self, hass):
        _, entities, session, device = await _setup(number_mod, hass, current_profile=2)
        session.select(0x01)
        session.params = _params(profile=1)  # stale
        assert _param(entities, 1).available is False
        session.params = _params(profile=2)  # reload for the new pair
        assert _param(entities, 1).available is True


class TestBrewSwitchReadiness:
    async def test_unavailable_on_profile_drift(self, hass):
        _, entities, session, device = await _setup(switch_mod, hass, current_profile=1)
        session.select(0x01)
        session.params = _params(profile=1)
        assert _brew_switch(entities).available is True
        device.current_profile = 2
        assert _brew_switch(entities).available is False

    async def test_turn_on_raises_when_params_missing(self, hass):
        _, entities, session, _ = await _setup(switch_mod, hass)
        session.select(0x01)
        with pytest.raises(HomeAssistantError, match="not loaded"):
            await _brew_switch(entities).async_turn_on()

    async def test_turn_on_raises_on_profile_drift(self, hass):
        _, entities, session, device = await _setup(switch_mod, hass, current_profile=1)
        session.select(0x01)
        session.params = _params(profile=1)
        device.current_profile = 2
        with pytest.raises(HomeAssistantError, match="not loaded"):
            await _brew_switch(entities).async_turn_on()

    async def test_turn_on_raises_while_loading(self, hass):
        _, entities, session, _ = await _setup(switch_mod, hass)
        session.select(0x01)
        session.params = _params(profile=1)
        session.loading = True
        with pytest.raises(HomeAssistantError, match="not loaded"):
            await _brew_switch(entities).async_turn_on()

    async def test_brews_after_reload_for_new_profile(self, hass):
        calls = []
        _, entities, session, _ = await _setup(
            switch_mod,
            hass,
            current_profile=2,
            brew=lambda *a, **kw: calls.append((a, kw)),
        )
        session.select(0x01)
        session.params = _params(profile=2)
        await _brew_switch(entities).async_turn_on()
        assert len(calls) == 1
