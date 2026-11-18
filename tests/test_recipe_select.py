"""Recipe select entity: catalogue options + session scoping (T012/US1)."""

from types import SimpleNamespace

import pytest
from cremalink.domain.device import RecipeParams
from custom_components.cremalink_ha import select as select_mod

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)


def _catalog(*bev_ids):
    return [SimpleNamespace(bev_id=i, kind="builtin", name=None) for i in bev_ids]


def _names(mapping=None):
    return (
        lambda bid: {"name": mapping.get(bid, f"Beverage {bid}")} if mapping else None
    )


async def _setup(hass, **dev):
    entry = make_entry()
    device = make_device(**dev)
    monitor = FakeMonitorData(status_name="ready")
    return await setup_entities(hass, entry, device, select_mod, monitor)


def _recipe_select(entities):
    return next(e for e in entities if e.unique_id == "entry1_recipe")


class TestRecipeSelect:
    async def test_options_from_catalogue(self, hass):
        _, entities = await _setup(
            hass,
            beverage_catalog=lambda **_: _catalog(0x01, 0xC8),
            brew_entry=_names({0x01: "Espresso", 0xC8: "Espresso Soul"}),
        )
        recipe = _recipe_select(entities)
        assert recipe.options == ["Espresso", "Espresso Soul"]
        assert recipe.current_option is None

    async def test_empty_catalogue_no_options(self, hass):
        _, entities = await _setup(hass, beverage_catalog=lambda **_: [])
        recipe = _recipe_select(entities)
        assert recipe.options == []

    async def test_options_available_in_standby_without_machine_read(self, hass):
        """The recipe list is static — standby must not block or query it."""
        calls = []

        def _catalog_fn(**kw):
            calls.append(kw)
            return _catalog(0x01)

        entry = make_entry()
        device = make_device(
            beverage_catalog=_catalog_fn, brew_entry=lambda bid: {"name": "Espresso"}
        )
        monitor = FakeMonitorData(status_name="in_standby")
        _, entities = await setup_entities(hass, entry, device, select_mod, monitor)
        recipe = _recipe_select(entities)
        assert recipe.options == ["Espresso"]
        assert calls == [{"fetch_priority": False}]  # zero machine reads

    @pytest.mark.parametrize(
        "status", ["in_standby", "going_to_sleep", "sleeping", "waking_up"]
    )
    async def test_recipe_select_unavailable_in_not_ready_states(self, status, hass):
        """Options stay populated but interaction is gated on readiness —
        same rule as the profile select."""
        device = make_device(
            beverage_catalog=lambda **_: _catalog(0x01),
            brew_entry=lambda bid: {"name": "Espresso"},
        )
        monitor = FakeMonitorData(status_name=status)
        _, entities = await setup_entities(
            hass, make_entry(), device, select_mod, monitor
        )
        recipe = _recipe_select(entities)
        assert recipe.options == ["Espresso"]
        assert recipe.available is False
        monitor.status_name = "ready"
        recipe._handle_coordinator_update()
        assert recipe.available is True

    async def test_priority_fetched_once_awake_and_throttled(self, hass):
        """Awake + order unknown → one fetch per 60 s window, not per poll."""
        calls = []

        def _catalog_fn(**kw):
            calls.append(kw)
            return _catalog(0x01)

        entry = make_entry()
        device = make_device(
            beverage_catalog=_catalog_fn,
            brew_entry=lambda bid: {"name": "Espresso"},
            recipe_priority_loaded=lambda profile_slot=None: False,
        )
        monitor = FakeMonitorData(status_name="ready")
        coordinator, entities = await setup_entities(
            hass, entry, device, select_mod, monitor
        )
        recipe = _recipe_select(entities)
        calls.clear()
        for _ in range(3):  # three coordinator cycles inside the window
            recipe._handle_coordinator_update()
            await hass.async_block_till_done()
        assert calls == [{"fetch_priority": True}]

    async def test_duplicate_labels_offered_once(self, hass):
        _, entities = await _setup(
            hass,
            beverage_catalog=lambda **_: _catalog(0x01, 0x02),
            brew_entry=lambda bid: {"name": "Same"},
        )
        recipe = _recipe_select(entities)
        assert recipe.options == ["Same"]

    async def test_select_option_sets_session(self, hass):
        params = RecipeParams(
            beverage_id=0x01,
            profile_slot=1,
            values={1: 60},
            bounds={1: (30, 40, 60)},
            source="stored",
        )
        _, entities = await _setup(
            hass,
            beverage_catalog=lambda **_: _catalog(0x01),
            brew_entry=lambda bid: {"name": "Espresso"},
            recipe_params=lambda bid, **_: params,
        )
        recipe = _recipe_select(entities)
        await recipe.async_select_option("Espresso")
        await hass.async_block_till_done()
        assert recipe.current_option == "Espresso"
        assert recipe.session.selected_beverage == 0x01
        assert recipe.session.params is params

    async def test_unknown_option_rejected(self, hass):
        _, entities = await _setup(
            hass,
            beverage_catalog=lambda **_: _catalog(0x01),
            brew_entry=lambda bid: {"name": "Espresso"},
        )
        recipe = _recipe_select(entities)
        with pytest.raises(ValueError):
            await recipe.async_select_option("Nope")

    async def test_switching_recipe_clears_overrides(self, hass):
        _, entities = await _setup(
            hass,
            beverage_catalog=lambda **_: _catalog(0x01, 0x02),
            brew_entry=lambda bid: {"name": f"B{bid}"},
            recipe_params=lambda bid, **_: RecipeParams(
                beverage_id=bid,
                profile_slot=1,
                values={},
                bounds={},
                source="stored",
            ),
        )
        recipe = _recipe_select(entities)
        await recipe.async_select_option("B1")
        await hass.async_block_till_done()
        recipe.session.set_override(1, 44)
        await recipe.async_select_option("B2")
        await hass.async_block_till_done()
        assert recipe.session.overrides == {}
        assert recipe.session.params.beverage_id == 0x02
