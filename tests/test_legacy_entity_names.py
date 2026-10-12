"""Stored custom names that freeze the old English default are cleared."""

import asyncio
import logging
from types import SimpleNamespace

import custom_components.cremalink_ha as init_mod
import pytest
from custom_components.cremalink_ha.const import DEVICE_NAME

ENGLISH = {
    "component.cremalink_ha.entity.sensor.cremalink_progress_percent.name": "Progress",
    "component.cremalink_ha.entity.sensor.cremalink_status_name.name": "Status",
    "component.cremalink_ha.entity.switch.power.name": "Power",
}


class _Registry:
    def __init__(self, entries):
        self.entries = entries
        self.updates = []

    def async_update_entity(self, entity_id, **changes):
        self.updates.append((entity_id, changes))


def _reg(entity_id, name, original_name, translation_key=None):
    return SimpleNamespace(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        original_name=original_name,
        translation_key=translation_key,
        device_id="dev1",
    )


@pytest.fixture
def run_migration(monkeypatch):
    """Run the migration against fake registries; returns the update list."""

    def _run(entries, *, device_name="AC000W040821014", name_by_user="Primadonna"):
        registry = _Registry(entries)
        device = SimpleNamespace(name=device_name, name_by_user=name_by_user)

        async def _translations(hass, language, category, integrations):
            assert (language, category) == ("en", "entity")
            return ENGLISH

        monkeypatch.setattr(init_mod.er, "async_get", lambda hass: registry)
        monkeypatch.setattr(
            init_mod.er,
            "async_entries_for_config_entry",
            lambda reg, entry_id: registry.entries,
        )
        monkeypatch.setattr(
            init_mod.dr,
            "async_get",
            lambda hass: SimpleNamespace(async_get=lambda device_id: device),
        )
        monkeypatch.setattr(
            init_mod.translation, "async_get_translations", _translations
        )
        entry = SimpleNamespace(
            entry_id="e1", title="AC000W040821014", data={DEVICE_NAME: "Soul"}
        )
        asyncio.run(init_mod._async_clear_legacy_entity_names(None, entry))
        return registry.updates

    return _run


class TestClearsStaleEnglishNames:
    def test_name_built_from_the_renamed_device_and_the_old_original_name(
        self, run_migration
    ):
        # First start with the new code: original_name is still English.
        updates = run_migration([_reg("sensor.k_status", "Primadonna Status", "Status")])
        assert updates == [("sensor.k_status", {"name": None})]

    def test_original_name_already_german_is_matched_via_the_english_translation(
        self, run_migration
    ):
        # A later start: registration already rewrote original_name to German,
        # the stale English custom name must still be recognised.
        updates = run_migration(
            [
                _reg(
                    "sensor.k_progress",
                    "Primadonna Progress",
                    "Fortschritt",
                    "cremalink_progress_percent",
                )
            ]
        )
        assert updates == [("sensor.k_progress", {"name": None})]

    @pytest.mark.parametrize(
        "stored",
        [
            "AC000W040821014 Power",  # integration title / device name
            "Soul Power",  # device_name from the entry data
            "Primadonna Power",  # device name chosen in the UI
            "Power",  # the bare English default
        ],
    )
    def test_every_form_of_the_old_default_is_cleared(self, run_migration, stored):
        updates = run_migration([_reg("switch.k_power", stored, "Power", "power")])
        assert updates == [("switch.k_power", {"name": None})]

    def test_a_logged_notice_names_the_entity(self, run_migration, caplog):
        with caplog.at_level(logging.INFO):
            run_migration([_reg("sensor.k_status", "Primadonna Status", "Status")])
        assert any("sensor.k_status" in r.getMessage() for r in caplog.records)


class TestKeepsRealCustomisations:
    @pytest.mark.parametrize(
        "stored",
        ["Kaffeemaschine Status", "Mein Status", "Primadonna Statusanzeige", "Status 2"],
    )
    def test_genuine_custom_names_stay(self, run_migration, stored):
        updates = run_migration([_reg("sensor.k_status", stored, "Status")])
        assert updates == []

    def test_entities_without_a_stored_name_are_untouched(self, run_migration):
        assert run_migration([_reg("sensor.k_status", None, "Status")]) == []

    def test_entities_without_translation_and_other_names_stay(self, run_migration):
        # A custom-map command has no translation key; its name is its own.
        updates = run_migration(
            [_reg("button.k_custom", "Meine Taste", "Brew Custom Drink")]
        )
        assert updates == []

    def test_only_the_stale_one_of_several_is_cleared(self, run_migration):
        updates = run_migration(
            [
                _reg("sensor.k_status", "Primadonna Status", "Status"),
                _reg("sensor.k_other", "Kaffeemaschine Fortschritt", "Progress"),
            ]
        )
        assert updates == [("sensor.k_status", {"name": None})]
