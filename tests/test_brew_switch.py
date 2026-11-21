"""Brew switch: one entity for brew + stop (replaces button.brew_recipe/cmd_stop)."""

import time

import pytest
from cremalink.domain.device import RecipeParams
from custom_components.cremalink_ha import switch as switch_mod
from homeassistant.exceptions import HomeAssistantError

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)


def _params(bev_id):
    return RecipeParams(
        beverage_id=bev_id,
        profile_slot=1,
        values={1: 60},
        bounds={1: (30, 40, 60)},
        source="stored",
    )


async def _setup(hass, monitor=None, **dev):
    entry = make_entry()
    device = make_device(**dev)
    coordinator, entities = await setup_entities(
        hass, entry, device, switch_mod, monitor or FakeMonitorData(status_name="ready")
    )
    session = hass.data["cremalink_ha"][entry.entry_id]["recipe_session"]
    return coordinator, entities, session


def _brew_switch(entities):
    return next(e for e in entities if e.unique_id == "entry1_brew_recipe")


class TestBrewSwitchState:
    async def test_created_with_recipe_session(self, hass):
        _, entities, _ = await _setup(hass)
        assert _brew_switch(entities) is not None

    async def test_off_when_ready_and_idle(self, hass):
        _, entities, _ = await _setup(hass)
        assert _brew_switch(entities).is_on is False

    async def test_on_while_brewing(self, hass):
        _, entities, _ = await _setup(
            hass, monitor=FakeMonitorData(status_name="ready", is_busy=True)
        )
        switch = _brew_switch(entities)
        assert switch.is_on is True
        assert switch.available is True  # stoppable even without selection

    async def test_unknown_without_status(self, hass):
        _, entities, _ = await _setup(hass, monitor=FakeMonitorData(status_name=None))
        assert _brew_switch(entities).is_on is None


class TestBrewSwitchAvailability:
    async def test_unavailable_without_selection(self, hass):
        _, entities, _ = await _setup(hass)
        assert _brew_switch(entities).available is False

    async def test_available_with_loaded_selection(self, hass):
        _, entities, session = await _setup(hass)
        session.select(0x01)
        session.params = _params(0x01)
        session.loading = False
        assert _brew_switch(entities).available is True

    async def test_unavailable_while_loading(self, hass):
        _, entities, session = await _setup(hass)
        session.select(0x01)
        session.loading = True
        assert _brew_switch(entities).available is False

    async def test_unavailable_in_standby_when_not_brewing(self, hass):
        _, entities, session = await _setup(
            hass, monitor=FakeMonitorData(status_name="in_standby", is_busy=False)
        )
        session.select(0x01)
        session.params = _params(0x01)
        assert _brew_switch(entities).available is False


class TestBrewSwitchActions:
    async def test_turn_on_brews_with_session_values(self, hass):
        calls = []
        _, entities, session = await _setup(
            hass, brew=lambda *a, **kw: calls.append((a, kw))
        )
        session.select(0xC8)
        session.params = _params(0xC8)
        session.loading = False
        session.set_override(1, 44)
        await _brew_switch(entities).async_turn_on()
        assert calls == [((0xC8,), {"overrides": {1: 44}, "params": session.params})]

    async def test_turn_on_without_selection_raises(self, hass):
        _, entities, _ = await _setup(hass)
        with pytest.raises(HomeAssistantError, match="Select a recipe"):
            await _brew_switch(entities).async_turn_on()

    async def test_turn_on_while_busy_raises(self, hass):
        _, entities, session = await _setup(
            hass, monitor=FakeMonitorData(status_name="ready", is_busy=True)
        )
        session.selected_beverage = 1
        with pytest.raises(HomeAssistantError, match="busy"):
            await _brew_switch(entities).async_turn_on()

    async def test_turn_off_sends_stop(self, hass):
        calls = []
        _, entities, _ = await _setup(hass, do=lambda cmd: calls.append(cmd))
        await _brew_switch(entities).async_turn_off()
        assert calls == ["stop"]

    async def test_turn_off_while_brewing_sends_stop(self, hass):
        calls = []
        _, entities, _ = await _setup(
            hass,
            monitor=FakeMonitorData(status_name="ready", is_busy=True),
            do=lambda cmd: calls.append(cmd),
        )
        await _brew_switch(entities).async_turn_off()
        assert calls == ["stop"]


class TestBrewSwitchPending:
    async def test_stays_off_after_stop_while_monitor_still_reports_brewing(self, hass):
        """Stop must not snap back on while the monitor still says brewing
        (production 2026-11-21: the poll right after stop flipped the
        switch back on before the machine confirmed the stop)."""
        coordinator, entities, _ = await _setup(
            hass, monitor=FakeMonitorData(status_name="ready", is_busy=True)
        )
        switch = _brew_switch(entities)
        await switch.async_turn_off()
        assert switch.is_on is False
        coordinator.data = FakeMonitorData(status_name="ready", is_busy=True)
        switch._handle_coordinator_update()
        assert switch.is_on is False

    async def test_pending_clears_when_monitor_confirms_stop(self, hass):
        coordinator, entities, _ = await _setup(
            hass, monitor=FakeMonitorData(status_name="ready", is_busy=True)
        )
        switch = _brew_switch(entities)
        await switch.async_turn_off()
        coordinator.data = FakeMonitorData(status_name="rinsing", is_busy=True)
        assert switch.is_on is False
        assert switch._pending is None

    async def test_pending_expiry_returns_monitor_truth(self, hass, monkeypatch):
        """A stop the machine never applied must not hide forever."""
        _, entities, _ = await _setup(
            hass, monitor=FakeMonitorData(status_name="ready", is_busy=True)
        )
        switch = _brew_switch(entities)
        await switch.async_turn_off()
        later = time.monotonic() + switch_mod.BREW_PENDING_SECONDS + 1
        monkeypatch.setattr(switch_mod.time, "monotonic", lambda: later)
        assert switch.is_on is True

    async def test_on_pending_until_monitor_confirms_brew(self, hass):
        """After brew the switch shows on even while the monitor has not
        caught up yet — mirrors the power-switch pending semantics."""
        coordinator, entities, session = await _setup(hass)
        session.select(0x01)
        session.params = _params(0x01)
        session.loading = False
        switch = _brew_switch(entities)
        await switch.async_turn_on()
        assert switch.is_on is True
        coordinator.data = FakeMonitorData(status_name="ready", is_busy=True)
        switch._handle_coordinator_update()
        assert switch.is_on is True
        assert switch._pending is None
