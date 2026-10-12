"""Entity translations: every entity has an English and a German name/state."""

import json
from pathlib import Path

import cremalink.devices as devices_pkg
from cremalink.ecam.monitor_bits import ALARM_BITS, SWITCH_BITS
from cremalink.ecam.statistics import CLOUD_COUNTER_CANDIDATES, STAT_LABELS
from custom_components.cremalink_ha import binary_sensor as bs_mod
from custom_components.cremalink_ha import button as button_mod
from custom_components.cremalink_ha import select as select_mod
from custom_components.cremalink_ha import sensor as sensor_mod
from custom_components.cremalink_ha import switch as switch_mod
from custom_components.cremalink_ha.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_CLOUD,
    TRANSLATED_COMMANDS,
)

from tests.helpers import (
    FakeEntry,
    FakeHass,
    FakeMonitorData,
    make_device,
    setup_entities,
)

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "cremalink_ha"
STRINGS = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
EN = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
DE = json.loads((COMPONENT / "translations" / "de.json").read_text(encoding="utf-8"))

POWER_COMMANDS = {"wakeup", "standby", "refresh"}


def _map_commands():
    commands = set()
    for path in Path(devices_pkg.__file__).parent.glob("*.json"):
        commands |= set(json.loads(path.read_text(encoding="utf-8"))["command_map"])
    return commands - POWER_COMMANDS


def _setup(module, *, cloud=False, **dev):
    device = make_device(**dev)
    device.get_commands = lambda: sorted(_map_commands())
    data = {CONF_CONNECTION_TYPE: CONNECTION_CLOUD} if cloud else {}
    _, entities = setup_entities(
        FakeHass(),
        FakeEntry(data=data),
        device,
        module,
        FakeMonitorData(status_name="ready"),
    )
    return entities


def _device_configurations():
    """One entity list per device configuration the integration can create."""
    all_cloud_datapoints = [
        name for names in CLOUD_COUNTER_CANDIDATES.values() for name in names
    ]
    return [
        _setup(sensor_mod),
        _setup(
            sensor_mod,
            cloud=True,
            statistics_source="cloud_counters",
            statistics_datapoints=all_cloud_datapoints,
        ),
        _setup(bs_mod),
        _setup(select_mod),
        _setup(button_mod),
        _setup(switch_mod),
    ]


def _entity_section(translations):
    return translations["entity"]


class TestCoverage:
    def test_strings_and_english_translation_are_identical(self):
        assert STRINGS == EN

    def test_every_entity_is_translated_to_english_and_german(self):
        checked = 0
        for entities in _device_configurations():
            for entity in entities:
                key = entity.translation_key
                assert entity.has_entity_name, entity.unique_id
                assert key, f"{entity.unique_id} has no translation key"
                domain = entity._domain
                for name, translations in (("en", EN), ("de", DE)):
                    entry = _entity_section(translations)[domain].get(key)
                    assert entry and entry.get("name"), f"{name}:{domain}.{key}"
                checked += 1
        assert checked > 100  # all platforms, statistics and bit sensors included

    def test_german_mirrors_the_english_structure(self):
        en, de = _entity_section(EN), _entity_section(DE)
        assert de.keys() == en.keys()
        for domain, keys in en.items():
            assert de[domain].keys() == keys.keys(), domain
            for key, entry in keys.items():
                assert de[domain][key].keys() == entry.keys(), f"{domain}.{key}"
                assert (
                    de[domain][key].get("state", {}).keys()
                    == entry.get("state", {}).keys()
                ), f"{domain}.{key} states"

    def test_names_are_unique_within_one_device(self):
        for translations in (EN, DE):
            section = _entity_section(translations)
            for entities in _device_configurations():
                names = [
                    section[e._domain][e.translation_key]["name"] for e in entities
                ]
                assert len(names) == len(set(names)), sorted(names)

    def test_german_is_really_german(self):
        de = _entity_section(DE)
        assert de["switch"]["power"]["name"] == "Ein/Aus"
        assert de["select"]["profile"]["name"] == "Profil"
        assert de["select"]["setting_water_hardness"]["name"] == "Wasserhärte"
        assert de["sensor"]["cremalink_status_name"]["state"]["ready"] == "Bereit"
        assert de["button"]["cmd_stop"]["name"] == "Stopp Zubereitung"
        assert de["binary_sensor"]["is_watertank_empty"]["name"] == "Wassertank leer"

    def test_german_controls_sort_power_then_stop_then_the_recipes(self):
        # Home Assistant lists a device's controls alphabetically by entity
        # name (Intl.Collator, no sort key exists), so the German names are
        # chosen to put power and stop above every recipe.
        de = _entity_section(DE)
        power = de["switch"]["power"]["name"]
        stop = de["button"]["cmd_stop"]["name"]
        recipes = [
            entry["name"] for key, entry in de["button"].items() if key != "cmd_stop"
        ]
        assert len(recipes) == len(TRANSLATED_COMMANDS) - 1
        assert power.casefold() < stop.casefold() < min(r.casefold() for r in recipes)
        assert min(recipes, key=str.casefold).startswith("Zubereiten: ")


class TestEnglishNamesAreUnchanged:
    """Switching to translations must not rename anything for English users."""

    def test_statistics_names_follow_the_label(self):
        sensors = _entity_section(EN)["sensor"]
        for label, _unit in STAT_LABELS.values():
            assert sensors[f"stat_{label}"]["name"] == label.replace("_", " ").title()
        for logical in CLOUD_COUNTER_CANDIDATES:
            assert (
                sensors[f"stat_{logical}"]["name"] == logical.replace("_", " ").title()
            )

    def test_bit_sensor_names_follow_the_library_labels(self):
        names = _entity_section(EN)["binary_sensor"]
        shared = {b.key for b in SWITCH_BITS.values()} & {
            b.key for b in ALARM_BITS.values()
        }
        for source, bits in (("switch", SWITCH_BITS), ("alarm", ALARM_BITS)):
            for bit in bits.values():
                expected = f"{bit.label} ({source})" if bit.key in shared else bit.label
                assert names[f"{source}_{bit.key}"]["name"] == expected

    def test_brew_button_names(self):
        buttons = _entity_section(EN)["button"]
        for command in TRANSLATED_COMMANDS - {"stop"}:
            expected = f"Brew {command.replace('_', ' ').title()}"
            assert buttons[f"cmd_{command}"]["name"] == expected
        assert buttons["cmd_stop"]["name"] == "Stop brewing"


class TestCommands:
    def test_every_command_of_every_packaged_map_is_translated(self):
        missing = _map_commands() - TRANSLATED_COMMANDS
        assert not missing, f"commands without translation: {sorted(missing)}"
        for command in TRANSLATED_COMMANDS:
            assert f"cmd_{command}" in _entity_section(EN)["button"]
            assert f"cmd_{command}" in _entity_section(DE)["button"]

    def test_command_of_a_custom_map_keeps_a_generated_name(self):
        device = make_device()
        device.get_commands = lambda: ["custom_drink"]
        _, entities = setup_entities(
            FakeHass(),
            FakeEntry(),
            device,
            button_mod,
            FakeMonitorData(status_name="ready"),
        )
        (button,) = entities
        assert button.translation_key is None
        assert button.name == "Brew Custom Drink"


class TestStatisticsStateClass:
    def test_state_readings_are_not_counters(self):
        entities = _device_configurations()[1]  # cloud counters
        by_key = {e.translation_key: e for e in entities}
        assert by_key["stat_descale_status"].state_class is None
        assert by_key["stat_water_hardness"].state_class is None
        assert by_key["stat_espresso"].state_class == "total_increasing"
        assert by_key["stat_descales"].state_class == "total_increasing"
