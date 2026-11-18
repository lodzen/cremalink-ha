"""Parameter number entities: bounds, display, override capture (T016/US2)."""

from cremalink.domain.device import RecipeParams
from cremalink.ecam.params import PARAMS
from custom_components.cremalink_ha import number as number_mod
from custom_components.cremalink_ha.const import DOMAIN
from homeassistant.helpers import entity_registry as er

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)

_PARAMS = RecipeParams(
    beverage_id=0x01,
    profile_slot=1,
    values={1: 60, 2: 3},
    bounds={1: (30, 40, 60), 2: (1, 3, 5), 24: (0, 1, 1)},
    source="stored",
)


async def _setup(hass, **dev):
    entry = make_entry()
    device = make_device(**dev)
    monitor = FakeMonitorData(status_name="ready")
    coordinator, entities = await setup_entities(
        hass, entry, device, number_mod, monitor
    )
    session = hass.data["cremalink_ha"][entry.entry_id]["recipe_session"]
    return coordinator, entities, session


def _param(entities, param_id):
    return next(e for e in entities if e.unique_id == f"entry1_recipe_param_{param_id}")


class TestParamNumbers:
    async def test_one_entity_per_adjustable_param(self, hass):
        _, entities, _ = await _setup(hass)
        uids = {e.unique_id for e in entities}
        assert uids == {f"entry1_recipe_param_{i}" for i in PARAMS}

    async def test_stale_param_registry_entries_removed(self, hass):
        """Orphaned blend/inversion/temp entities are swept on setup (R12)."""
        entry = make_entry()
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        for pid in (4, 12, 0):  # blend, inversion, temp — dropped from PARAMS
            ent_reg.async_get_or_create(
                "number", DOMAIN, f"entry1_recipe_param_{pid}", config_entry=entry
            )
        device = make_device()
        monitor = FakeMonitorData(status_name="ready")
        coordinator, entities = await setup_entities(
            hass, entry, device, number_mod, monitor
        )
        remaining = {
            reg.unique_id
            for reg in ent_reg.entities.values()
            if reg.domain == "number"
            and reg.unique_id.startswith("entry1_recipe_param_")
        }
        assert remaining == {f"entry1_recipe_param_{i}" for i in PARAMS}

    async def test_unavailable_without_loaded_params(self, hass):
        _, entities, session = await _setup(hass)
        session.select(0x01)  # selected but nothing loaded yet
        assert _param(entities, 1).available is False

    async def test_value_and_bounds_from_loaded_params(self, hass):
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0x01
        session.params = _PARAMS
        coffee = _param(entities, 1)
        assert coffee.available is True
        assert coffee.native_value == 60.0  # raw 60 = 60 ml (R11: raw = ml)
        assert coffee.native_min_value == 30.0
        assert coffee.native_max_value == 60.0

    async def test_param_not_in_recipe_unavailable(self, hass):
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0x01
        session.params = _PARAMS
        # param 15 (water) is not in an espresso's values/bounds
        assert _param(entities, 15).available is False

    async def test_degenerate_bounds_param_unavailable(self, hass):
        """Water (0,0,0) — degenerate descriptor range → hidden (R12)."""
        params = RecipeParams(
            beverage_id=0x01,
            profile_slot=1,
            values={1: 60, 2: 3, 15: 0},
            bounds={1: (30, 40, 60), 2: (1, 3, 5), 15: (0, 0, 0), 24: (0, 1, 1)},
            source="stored",
        )
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0x01
        session.params = params
        assert _param(entities, 15).available is False
        assert _param(entities, 1).available is True

    async def test_amount_zero_param_unavailable(self, hass):
        """def/current 0 quantity → hidden, like the app's mug-to-go (R12)."""
        params = RecipeParams(
            beverage_id=0x2E,
            profile_slot=1,
            values={1: 0, 2: 3},
            bounds={1: (40, 0, 240), 2: (1, 3, 5), 24: (0, 1, 1)},
            source="stored",
        )
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0x2E
        session.params = params
        assert _param(entities, 1).available is False
        assert _param(entities, 2).available is False

    async def test_bean_beverage_shows_coffee_only(self, hass):
        """BeanAdapt (id 200) gets coffee amount alone in the app (R12)."""
        params = RecipeParams(
            beverage_id=0xC8,
            profile_slot=1,
            values={1: 40, 2: 4},
            bounds={1: (30, 40, 60), 2: (1, 4, 5), 24: (0, 1, 1)},
            source="stored",
        )
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0xC8
        session.params = params
        assert _param(entities, 1).available is True
        assert _param(entities, 2).available is False

    async def test_set_value_records_raw_override_no_machine_write(self, hass):
        writes = []
        _, entities, session = await _setup(
            hass, brew=lambda *a, **kw: writes.append((a, kw))
        )
        session.selected_beverage = 0x01
        session.params = _PARAMS
        coffee = _param(entities, 1)
        await coffee.async_set_native_value(50)
        assert session.overrides == {1: 50}  # raw = ml directly (R11)
        assert writes == []  # transient: no machine write until brew
        assert coffee.native_value == 50.0

    async def test_set_value_clamps_to_bounds(self, hass):
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0x01
        session.params = _PARAMS
        coffee = _param(entities, 1)
        await coffee.async_set_native_value(999)
        assert session.overrides == {1: 60}  # clamped to raw max

    async def test_milk_display_scaling(self, hass):
        """Param 9 (milk) is seconds: raw deciseconds → display seconds."""
        params = RecipeParams(
            beverage_id=0x08,
            profile_slot=1,
            values={9: 120},
            bounds={9: (40, 80, 400), 24: (0, 1, 1)},
            source="stored",
        )
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0x08
        session.params = params
        milk = _param(entities, 9)
        assert milk.native_value == 12.0  # raw 120 → 12 s
        assert milk.native_step == 0.1
        await milk.async_set_native_value(15.0)
        assert session.overrides[9] == 150

    async def test_extra_attributes_expose_source(self, hass):
        _, entities, session = await _setup(hass)
        session.selected_beverage = 0x01
        session.params = _PARAMS
        attrs = _param(entities, 1).extra_state_attributes
        assert attrs["param_id"] == 1
        assert attrs["beverage_id"] == 0x01
        assert attrs["values_source"] == "stored"
        assert attrs["overridden"] is False
