"""Two config entries keep independent coordinator/entity state (T049)."""

from cremalink.ecam.statistics import interpret
from custom_components.cremalink_ha import sensor as sensor_mod
from custom_components.cremalink_ha.const import DOMAIN

from tests.helpers import (
    FakeEntry,
    FakeHass,
    FakeMonitorData,
    make_device,
    setup_entities,
)


def test_two_local_entries_independent_statistics():
    hass = FakeHass()
    entry_a = FakeEntry(entry_id="entry_a", title="Soul A")
    entry_b = FakeEntry(entry_id="entry_b", title="Soul B")
    device_a = make_device()
    device_b = make_device()

    coord_a, entities_a = setup_entities(
        hass, entry_a, device_a, sensor_mod, FakeMonitorData(status_name="ready")
    )
    coord_b, entities_b = setup_entities(
        hass, entry_b, device_b, sensor_mod, FakeMonitorData(status_name="in_standby")
    )

    # Entries registered under their own ids.
    assert hass.data[DOMAIN]["entry_a"]["coordinator"] is coord_a
    assert hass.data[DOMAIN]["entry_b"]["coordinator"] is coord_b

    # Statistics are per-entry: A fetched, B never fetched.
    coord_a.statistics = interpret([(43010, 42)], source="native", complete=True)
    sensor_a = next(
        e for e in entities_a if e.unique_id == "entry_a_stat_total_beverages"
    )
    sensor_b = next(
        e for e in entities_b if e.unique_id == "entry_b_stat_total_beverages"
    )
    assert sensor_a.native_value == 42
    assert sensor_b.native_value is None


def test_two_local_entries_independent_failures():
    hass = FakeHass()
    coord_a, entities_a = setup_entities(
        hass,
        FakeEntry(entry_id="entry_a"),
        make_device(),
        sensor_mod,
        FakeMonitorData(status_name="ready"),
    )
    _coord_b, entities_b = setup_entities(
        hass,
        FakeEntry(entry_id="entry_b"),
        make_device(),
        sensor_mod,
        FakeMonitorData(status_name="ready"),
    )

    coord_a.consecutive_failures = coord_a.failure_threshold
    sensor_a = entities_a[0]
    sensor_b = entities_b[0]
    assert sensor_a.available is False
    assert sensor_b.available is True


def test_two_local_entries_independent_standby_caches():
    hass = FakeHass()
    coord_a, entities_a = setup_entities(
        hass,
        FakeEntry(entry_id="entry_a"),
        make_device(),
        sensor_mod,
        FakeMonitorData(status_name="ready", accessory_name="latte_crema_hot"),
    )
    _, entities_b = setup_entities(
        hass,
        FakeEntry(entry_id="entry_b"),
        make_device(),
        sensor_mod,
        FakeMonitorData(status_name="ready", accessory_name="none"),
    )
    acc_a = next(e for e in entities_a if e.unique_id == "entry_a_accessory_name")
    acc_b = next(e for e in entities_b if e.unique_id == "entry_b_accessory_name")
    assert acc_a.native_value == "latte_crema_hot"
    assert acc_b.native_value == "none"
    # A goes standby: only A's cache engages.
    coord_a.data = FakeMonitorData(status_name="in_standby", accessory_name="none")
    assert acc_a.native_value == "latte_crema_hot"
    assert acc_b.native_value == "none"
