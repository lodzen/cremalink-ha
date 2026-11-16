"""Per-drink + retired brew/stop button removal (T012/US1)."""

from custom_components.cremalink_ha import button as button_mod
from homeassistant.helpers import entity_registry

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)

_COMMANDS = ["espresso", "espresso_soul", "stop", "wakeup", "standby"]
_COMMAND_MAP = {
    "espresso": {"beverage_id": 1, "action": 1},
    "espresso_soul": {"beverage_id": 200, "action": 1},
    "stop": {"beverage_id": 16, "action": 2},
    "wakeup": {"power": "wake"},
    "standby": {"power": "standby"},
}


async def _setup(hass, **dev):
    entry = make_entry()
    device = make_device(
        get_commands=lambda: list(_COMMANDS), command_map=_COMMAND_MAP, **dev
    )
    monitor = FakeMonitorData(status_name="ready")
    return await setup_entities(hass, entry, device, button_mod, monitor)


class TestBeverageButtonRemoval:
    async def test_beverage_and_stop_commands_create_no_buttons(self, hass):
        """select.recipe + switch.brew_recipe own brew/stop — the button
        platform keeps only non-beverage commands."""
        _, entities = await _setup(hass)
        uids = {e.unique_id for e in entities}
        assert not any("espresso" in u or "stop" in u for u in uids)
        assert "entry1_brew_recipe" not in uids

    async def test_stale_beverage_button_registry_entries_removed(self, hass):
        """Pre-registered per-drink/stop/brew buttons are swept."""
        entry = make_entry()
        entry.add_to_hass(hass)
        ent_reg = entity_registry.async_get(hass)
        for uid, eid in (
            ("entry1_cmd_espresso", "button.brew_espresso"),
            ("entry1_cmd_stop", "button.stop_brewing"),
            ("entry1_brew_recipe", "button.brew_recipe"),
        ):
            ent_reg.async_get_or_create(
                "button",
                "cremalink_ha",
                uid,
                config_entry=entry,
                suggested_object_id=eid.removeprefix("button."),
            )
        device = make_device(
            get_commands=lambda: list(_COMMANDS), command_map=_COMMAND_MAP
        )
        await setup_entities(
            hass, entry, device, button_mod, FakeMonitorData(status_name="ready")
        )
        registry_uids = {reg.unique_id for reg in ent_reg.entities.values()}
        assert "entry1_cmd_espresso" not in registry_uids
        assert "entry1_cmd_stop" not in registry_uids
        assert "entry1_brew_recipe" not in registry_uids
